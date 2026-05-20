#!/usr/bin/env python3
"""MD 파일에서 제목 / 본문 / 이미지 경로 추출."""
import argparse
import json
import re
import sys
from pathlib import Path


H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def extract(md_path: Path) -> dict:
    text = md_path.read_text()
    title_m = H1_RE.search(text)
    title = title_m.group(1).strip() if title_m else md_path.stem

    # 본문 — 첫 H1 줄 다음부터
    if title_m:
        body = text[title_m.end():].lstrip("\n")
    else:
        body = text

    # 이미지 추출
    images = []
    for m in IMG_RE.finditer(text):
        alt, src = m.group(1), m.group(2)
        is_local = not src.startswith(("http://", "https://", "data:"))
        images.append({"alt": alt, "src": src, "is_local": is_local})

    return {
        "title": title,
        "body": body,
        "images": images,
        "n_chars": len(body),
        "n_lines": body.count("\n") + 1,
        "n_local_images": sum(1 for i in images if i["is_local"]),
        "n_remote_images": sum(1 for i in images if not i["is_local"]),
    }


def main():
    parser = argparse.ArgumentParser(description="Extract title/body/images from MD.")
    parser.add_argument("md_path", help="MD 파일 경로")
    parser.add_argument("--json-only", action="store_true",
                        help="결과를 JSON으로만 출력 (default: 사람이 읽기 좋은 요약)")
    args = parser.parse_args()

    md_path = Path(args.md_path)
    if not md_path.exists():
        print(f"❌ Not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    info = extract(md_path)

    if args.json_only:
        # body는 너무 길어서 제외
        out = {k: v for k, v in info.items() if k != "body"}
        out["body_preview"] = info["body"][:200]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"제목: {info['title']}")
        print(f"본문: {info['n_chars']:,} chars / {info['n_lines']} lines")
        print(f"이미지: {len(info['images'])}개 "
              f"(로컬 {info['n_local_images']} / 원격 {info['n_remote_images']})")
        if info["n_local_images"] > 0:
            print("\n⚠ 로컬 이미지 (Notion API로 직접 업로드 불가):")
            for img in info["images"]:
                if img["is_local"]:
                    print(f"  - {img['src']}")


if __name__ == "__main__":
    main()
