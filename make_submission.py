"""Build and validate submission.zip from submission/.

Checks mirror HARNESS_README.md §2.2, §2.4, §3.2 and §3.4 (see NOTES.md).
    python make_submission.py           # validate + write submission.zip
    python make_submission.py --check   # validate only
    python make_submission.py --hash    # print config hash for EXPERIMENTS.md
"""
import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "submission"
OUT = ROOT / "submission.zip"

MAX_TOTAL_BYTES = 3 * 1024**3  # unpacked, adapters included
MAX_FILES = 10_000
MAX_YAML_BYTES = 50 * 1024**2
MAX_SKILL_BYTES = 50 * 1024**2
MAX_LORA_RANK = 128
MAX_GEN_TOKENS = 32_768
ROOT_CONFIGS = ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
ADAPTER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# google-adk Frontmatter: kebab-case only (snake_case sits behind a feature flag that is off in the harness).
SKILL_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
PROVIDER_PREFIX = re.compile(r"^(openai|google|hosted_vllm|custom)/")
BASE_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}


def files(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.name != ".gitkeep")


def declared_models(src: Path) -> set[str]:
    # Plain-text scan of `model:` keys; good enough without a YAML dependency.
    found = set()
    for y in src.rglob("*.y*ml"):
        for m in re.finditer(r"^\s*model:\s*['\"]?([^\s'\"#]+)", y.read_text(encoding="utf-8"), re.M):
            found.add(PROVIDER_PREFIX.sub("", m.group(1)))
    return found


def safetensors_ok(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            json.loads(f.read(n))
        return True
    except Exception:
        return False


def skill_frontmatter_errors(d: Path) -> list[str]:
    """What google-adk's load_skill_from_dir rejects: no frontmatter, bad name, name != dir name, no description."""
    text = (d / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return [f"skill {d.name}: SKILL.md must start with --- frontmatter ---"]
    fields = dict(re.findall(r"^([A-Za-z_-]+):\s*(.*?)\s*$", m.group(1), re.M))
    name, errors = fields.get("name", "").strip("'\""), []
    if not SKILL_NAME.fullmatch(name) or len(name) > 64:
        errors.append(f"skill {d.name}: name {name!r} must be kebab-case (a-z, 0-9, hyphens), <= 64 chars")
    if name != d.name:
        errors.append(f"skill {d.name}: frontmatter name {name!r} must equal the directory name")
    if not fields.get("description"):
        errors.append(f"skill {d.name}: frontmatter needs a description")
    return errors


def validate(src: Path) -> list[str]:
    errors = []
    roots = [c for c in ROOT_CONFIGS if (src / c).is_file()]
    if len(roots) != 1:
        errors.append(f"need exactly one root config {ROOT_CONFIGS}, found {roots or 'none'}")

    all_files = files(src)
    if len(all_files) > MAX_FILES:
        errors.append(f"{len(all_files)} files > {MAX_FILES}")
    total = 0
    for p in all_files:
        rel = p.relative_to(src)
        total += p.stat().st_size
        if p.is_symlink() or ".." in rel.parts:
            errors.append(f"symlink / path traversal: {rel}")
        if p.suffix.lower() not in ALLOWED_EXT:
            errors.append(f"disallowed extension: {rel}")
        if p.suffix in (".yaml", ".yml") and p.stat().st_size > MAX_YAML_BYTES:
            errors.append(f"yaml > 50 MiB: {rel}")
        if p.suffix in (".yaml", ".yml"):
            for m in re.finditer(r"!include\s+(\S+)", p.read_text(encoding="utf-8")):
                target = (p.parent / m.group(1)).resolve()
                if not target.is_relative_to(src.resolve()):
                    errors.append(f"{rel}: !include escapes submission root: {m.group(1)}")
                elif not target.is_file():
                    errors.append(f"{rel}: !include target missing: {m.group(1)}")
            for m in re.finditer(r"(max_output_tokens|thinking_budget):\s*(\d+)", p.read_text(encoding="utf-8")):
                if int(m.group(2)) > MAX_GEN_TOKENS:
                    errors.append(f"{rel}: {m.group(1)}={m.group(2)} > {MAX_GEN_TOKENS}")
            if re.search(r"^\s*thinking_level:", p.read_text(encoding="utf-8"), re.M):
                print(f"WARN: {rel}: thinking_level is ignored over vLLM; use thinking_budget + include_thoughts")
    if total >= MAX_TOTAL_BYTES:
        errors.append(f"unpacked size {total} >= 3 GiB")

    adapters = src / "adapters"
    if adapters.is_dir():
        for d in (d for d in adapters.iterdir() if d.is_dir()):
            if not ADAPTER_NAME.fullmatch(d.name):
                errors.append(f"adapter name invalid: {d.name}")
            st, cfg = d / "adapter_model.safetensors", d / "adapter_config.json"
            if not st.is_file() or not safetensors_ok(st):
                errors.append(f"adapter {d.name}: missing or unreadable adapter_model.safetensors")
            if not cfg.is_file():
                errors.append(f"adapter {d.name}: no adapter_config.json")
            else:
                r = json.loads(cfg.read_text(encoding="utf-8")).get("r", 0)
                if r > MAX_LORA_RANK:
                    errors.append(f"adapter {d.name}: rank {r} > {MAX_LORA_RANK}")
    skills = src / "skills"
    if skills.is_dir():
        for d in (d for d in skills.iterdir() if d.is_dir()):
            if not (d / "SKILL.md").is_file():
                errors.append(f"skill {d.name}: no SKILL.md")
            else:
                errors += skill_frontmatter_errors(d)
            if sum(p.stat().st_size for p in files(d)) > MAX_SKILL_BYTES:
                errors.append(f"skill {d.name}: > 50 MiB")

    models = declared_models(src)
    if len(models) != 1:
        errors.append(f"need exactly one base model across all agents, found {sorted(models) or 'none'}")
    elif not models <= BASE_MODELS:
        errors.append(f"model not allowed in competition: {models}")
    return errors


def config_hash(src: Path) -> str:
    h = hashlib.sha256()
    for p in files(src):
        h.update(p.relative_to(src).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--hash", action="store_true")
    ap.add_argument("--src", type=Path, default=SRC)
    args = ap.parse_args()

    if args.hash:
        print(config_hash(args.src))
        return 0
    errors = validate(args.src)
    for e in errors:
        print("ERROR:", e)
    if errors:
        return 1
    if args.check:
        print("ok")
        return 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files(args.src):
            z.write(p, p.relative_to(args.src).as_posix())
    print(f"wrote {OUT.name} ({OUT.stat().st_size} bytes, hash {config_hash(args.src)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
