"""snapshot.py — 冻结输入快照（redesign-decisions.md D6）。

复现契约的载体：
    模型筛选结果一旦产生，**立即冻结**为输入快照；此后的复算、验证、重新出报告
    全部针对该快照。承诺"从快照到结论"逐字节可复现；**不承诺**"模型这次筛了什么"
    跨次一致。

快照目录结构（项目级，可跨 run 复用）::

    snapshots/<snapshot_id>/
    ├── manifest.json      快照元数据 + 文件清单 + 哈希 + 判断批次引用
    ├── literature.json    文献腿产出（检索到的论文元数据 + 裁决标注）
    ├── materials.csv      数据腿产出（已映射为标准列的材料数值）
    └── judgments.jsonl    该轮检索的判断批次（tier=judgment，随快照自包含）

设计要点：
- 快照**自包含**判断批次：既保证判据 4（删除判断记录则报告生成失败），
  也让复算 run 能把判断重新登记进自己的账本，形成独立可审计的闭环。
- **内容哈希只覆盖文件**，不包含时间戳等易变字段（否则确定性契约失效）。
- 校验为强校验：任一文件被改动或丢失 → verify() 失败。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time

from .util import sha256_file

SNAPSHOT_DIRNAME = "snapshots"

MATERIALS_FILE = "materials.csv"
LITERATURE_FILE = "literature.json"
JUDGMENTS_FILE = "judgments.jsonl"
MANIFEST_FILE = "manifest.json"

TRACKED_FILES = (MATERIALS_FILE, LITERATURE_FILE, JUDGMENTS_FILE)


class SnapshotError(RuntimeError):
    pass


def _utc_now_str() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_snapshot_id() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"snap-{stamp}-{secrets.token_hex(3)}"


def snapshots_root(root: str) -> str:
    return os.path.join(root, SNAPSHOT_DIRNAME)


def snapshot_dir(root: str, snapshot_id: str) -> str:
    return os.path.join(snapshots_root(root), snapshot_id)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _count_csv_rows(text: str) -> int:
    """统计 CSV 数据行数（不含表头），容忍 BOM 与空行。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return max(0, len(lines) - 1)


def content_hash_of(files: dict[str, str]) -> str:
    """对 {文件名: sha256} 计算聚合内容哈希（按文件名排序，确定性）。"""
    parts = [f"{name}:{files[name]}" for name in sorted(files)]
    return _sha256_bytes("\n".join(parts).encode("utf-8"))


class Snapshot:
    """一个冻结输入快照的读写句柄。"""

    def __init__(self, root: str, snapshot_id: str):
        self.root = root
        self.snapshot_id = snapshot_id
        self.dir = snapshot_dir(root, snapshot_id)

    # ---------- 路径 ----------

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.dir, MANIFEST_FILE)

    def file_path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    # ---------- 写 ----------

    def write(
        self,
        materials_csv: str,
        literature: dict,
        judgments: list[dict],
        sources: list[dict] | None = None,
        producer: str = "unspecified",
        stats: dict | None = None,
    ) -> dict:
        """落盘快照并返回 manifest。幂等性不做保证——同一 id 重复写会覆盖。"""
        if os.path.exists(self.dir) and os.path.exists(self.manifest_path):
            raise SnapshotError(f"snapshot already exists: {self.snapshot_id}")
        os.makedirs(self.dir, exist_ok=True)

        materials_bytes = materials_csv.encode("utf-8")
        literature_bytes = json.dumps(literature, ensure_ascii=False,
                                      indent=2, sort_keys=True).encode("utf-8") + b"\n"
        judgments_bytes = b"".join(
            json.dumps(j, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
            for j in judgments
        )

        _write_bytes(self.file_path(MATERIALS_FILE), materials_bytes)
        _write_bytes(self.file_path(LITERATURE_FILE), literature_bytes)
        _write_bytes(self.file_path(JUDGMENTS_FILE), judgments_bytes)

        file_hashes = {
            MATERIALS_FILE: _sha256_bytes(materials_bytes),
            LITERATURE_FILE: _sha256_bytes(literature_bytes),
            JUDGMENTS_FILE: _sha256_bytes(judgments_bytes),
        }
        manifest = {
            "snapshot_id": self.snapshot_id,
            "created_at": _utc_now_str(),
            "producer": producer,
            "sources": sources or [],
            "files": [
                {"name": MATERIALS_FILE, "sha256": file_hashes[MATERIALS_FILE],
                 "bytes": len(materials_bytes),
                 "rows": _count_csv_rows(materials_csv)},
                {"name": LITERATURE_FILE, "sha256": file_hashes[LITERATURE_FILE],
                 "bytes": len(literature_bytes)},
                {"name": JUDGMENTS_FILE, "sha256": file_hashes[JUDGMENTS_FILE],
                 "bytes": len(judgments_bytes), "count": len(judgments)},
            ],
            "content_sha256": content_hash_of(file_hashes),
            "judgment_batch": {
                "count": len(judgments),
                "kinds": sorted({j.get("kind", "") for j in judgments}),
            },
            "stats": stats or {},
        }
        with open(self.manifest_path, "w", encoding="utf-8", newline="") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        return manifest

    # ---------- 读 ----------

    def exists(self) -> bool:
        return os.path.exists(self.manifest_path)

    def load(self) -> dict:
        if not self.exists():
            raise SnapshotError(f"snapshot not found: {self.snapshot_id}")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def materials_path(self) -> str:
        p = self.file_path(MATERIALS_FILE)
        if not os.path.exists(p):
            raise SnapshotError(f"snapshot {self.snapshot_id} missing {MATERIALS_FILE}")
        return p

    def literature(self) -> dict:
        with open(self.file_path(LITERATURE_FILE), "r", encoding="utf-8") as f:
            return json.load(f)

    def judgments(self) -> list[dict]:
        p = self.file_path(JUDGMENTS_FILE)
        if not os.path.exists(p):
            return []
        out = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    # ---------- 校验 ----------

    def verify(self) -> tuple[bool, list[str]]:
        """强校验：逐文件重算 sha256 并比对 content_sha256。"""
        problems: list[str] = []
        if not self.exists():
            return False, [f"manifest missing: {self.manifest_path}"]
        manifest = self.load()
        declared = {f["name"]: f["sha256"] for f in manifest.get("files", [])}
        actual: dict[str, str] = {}
        for name in TRACKED_FILES:
            p = self.file_path(name)
            if not os.path.exists(p):
                problems.append(f"file missing: {name}")
                continue
            actual[name] = sha256_file(p)
            if name in declared and declared[name] != actual[name]:
                problems.append(
                    f"hash mismatch: {name} "
                    f"declared={declared[name][:16]} actual={actual[name][:16]}")
        if len(actual) == len(TRACKED_FILES):
            ch = content_hash_of(actual)
            if ch != manifest.get("content_sha256"):
                problems.append(
                    f"content hash mismatch: declared="
                    f"{(manifest.get('content_sha256') or '')[:16]} actual={ch[:16]}")
        return (len(problems) == 0, problems)

    def require_judgments(self) -> None:
        """判据 4 前置：快照必须携带判断批次，否则报告不得生成。"""
        if not self.judgments():
            raise SnapshotError(
                f"snapshot {self.snapshot_id} carries no judgment batch: "
                f"report generation refused (model filtering must be traceable)")

    def register_judgments_into(self, prov) -> list[str]:
        """把快照的判断批次重新登记进指定账本（tier=judgment），返回新 EV 列表。

        使复算 run 的账本自包含、可独立审计。
        """
        ev_ids: list[str] = []
        for j in self.judgments():
            meta = dict(j.get("meta") or {})
            ev = prov.append_judgment(
                judgment_kind=j.get("kind", "relevance"),
                producer_step=j.get("producer_step", "P1_lit_search"),
                subject=(meta.pop("subject", "") or j.get("ref", "")),
                verdict=meta.pop("verdict", ""),
                rationale=meta.pop("rationale", ""),
                meta=meta,
            )
            ev_ids.append(ev)
        return ev_ids


# ---------- 发现与枚举 ----------


def list_snapshots(root: str) -> list[str]:
    base = snapshots_root(root)
    if not os.path.isdir(base):
        return []
    ids = [d for d in os.listdir(base)
           if os.path.isdir(os.path.join(base, d))
           and re.match(r"^snap-", d)]
    return sorted(ids)


def latest_snapshot_id(root: str) -> str:
    """按目录名（内含时间戳）取最新快照；无快照返回空串。"""
    ids = list_snapshots(root)
    return ids[-1] if ids else ""


def open_snapshot(root: str, snapshot_id: str = "") -> Snapshot:
    """打开指定快照；snapshot_id 为空时取最新。"""
    sid = snapshot_id or latest_snapshot_id(root)
    if not sid:
        raise SnapshotError(
            f"no snapshot available under {snapshots_root(root)} "
            f"(run the retrieval/freeze step first, or use --snapshot)")
    return Snapshot(root, sid)
