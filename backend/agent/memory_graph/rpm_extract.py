"""无第三方依赖的 RPM 解包器（供 install_memory_infra.sh 使用）。

当 dist.neo4j.org 等 tarball 源被封锁时，从 yum.neo4j.com 下载社区版 RPM
并解出服务端文件，重组为 tarball 布局（bin/lib/conf/data/logs/run/...）。

仅用标准库（struct/zlib/lzma），无需 rpm/rpm2cpio/cpio 等系统工具。
"""
import argparse
import lzma
import os
import stat
import struct
import sys
import zlib

MAGIC = b"\x8e\xad\xe8"

# 需要从 RPM 中取出的前缀
KEEP_PREFIXES = ("var/lib/neo4j", "usr/share/neo4j", "etc/neo4j")


def _read_header(fp, offset):
    """解析 offset 处的 header，返回 (header_end_offset)。"""
    fp.seek(offset)
    magic = fp.read(3)
    if magic != MAGIC:
        raise ValueError(f"offset {offset}: 不是 RPM header (magic={magic!r})")
    fp.read(1)  # version
    fp.read(4)  # reserved
    nindex, hsize = struct.unpack(">II", fp.read(8))
    fp.read(nindex * 16)  # index entries
    data_end = offset + 16 + nindex * 16 + hsize
    return data_end


def _find_payload_offset(fp, search_from: int) -> int:
    """在 header 之后搜索 payload 的压缩魔数（gzip/xz），比按 8 对齐推算更稳。"""
    fp.seek(search_from)
    blob = fp.read(1 << 20)
    for magic in (b"\x1f\x8b\x08", b"\xfd7zXZ"):
        idx = blob.find(magic)
        if idx != -1:
            return search_from + idx
    raise ValueError("未找到 payload 压缩流（gzip/xz 魔数）")


def _payload_stream(fp, payload_offset):
    """按 gzip / xz 顺序尝试解压 payload，返回 (decompressor, fp)。"""
    payload_offset = _find_payload_offset(fp, payload_offset)
    fp.seek(payload_offset)
    head = fp.read(2)
    fp.seek(payload_offset)
    if head == b"\x1f\x8b":
        return zlib.decompressobj(16 + zlib.MAX_WBITS), fp
    return lzma.LZMADecompressor(), fp


def _iter_cpio(fp, decomp):
    """解析 cpio newc 流，产出 (mode, name, data_bytes)。"""
    while True:
        hdr = fp.read(6)
        if not hdr:
            break
        if hdr == b"070701":
            # newc：13 个 8 字节十六进制 ASCII 字段（共 104 字节）
            meta = fp.read(104)
            fields = [int(meta[i * 8:(i + 1) * 8], 16) for i in range(13)]
            (ino, mode, uid, gid, nlink, mtime, filesize,
             devmajor, devminor, rdevmajor, rdevminor, namesize, check) = fields
            name = fp.read(namesize)[:-1]  # 去掉结尾 NUL
            name = name.decode("utf-8", errors="replace")
            fp.read((4 - ((6 + 104 + namesize) % 4)) % 4)  # name 对齐到 4
            data = fp.read(filesize) if filesize else b""
            fp.read((4 - (filesize % 4)) % 4)  # data 对齐到 4
            yield mode, name, data
            if name == "TRAILER!!!":
                break
        elif hdr == b"070702":  # crc 变体
            raise ValueError("暂不支持 cpio crc 格式")
        else:
            # gzip 流可能被提前截断的防御
            break


def extract(rpm_path: str, dest_dir: str, layout_home: str) -> None:
    """解包 RPM 并把服务端文件重组为 tarball 布局到 layout_home。"""
    os.makedirs(layout_home, exist_ok=True)
    with open(rpm_path, "rb") as fp:
        # lead 96B -> signature header -> main header -> payload
        sig_end = _read_header(fp, 96)
        head_end = _read_header(fp, sig_end)
        # payload 紧接 header 之后（可能有不固定对齐），从 head_end 起搜索压缩魔数
        decomp, _ = _payload_stream(fp, head_end)

        # 分批解压 feed
        chunk_size = 1 << 20
        cpio_fp = _DecompReader(fp, decomp, 0, chunk_size)

        for mode, name, data in _iter_cpio(cpio_fp, decomp):
            name = name.lstrip("./")
            if not name.startswith(KEEP_PREFIXES):
                continue
            # 映射到 tarball 布局
            if name.startswith("usr/share/neo4j/"):
                rel = name[len("usr/share/neo4j/"):]
                dest = os.path.join(layout_home, rel)
            elif name.startswith("etc/neo4j/"):
                rel = name[len("etc/neo4j/"):]
                dest = os.path.join(layout_home, "conf", rel)
            elif name.startswith("var/lib/neo4j/"):
                rel = name[len("var/lib/neo4j/"):]
                dest = os.path.join(layout_home, rel)
            else:
                continue

            ftype = (mode >> 12) & 0xF
            if ftype == stat.S_IFDIR >> 12:
                os.makedirs(dest, exist_ok=True)
            elif ftype == stat.S_IFREG >> 12:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as out:
                    out.write(data)
                perms = mode & 0o777
                if perms:
                    try:
                        os.chmod(dest, perms)
                    except OSError:
                        pass
            elif ftype == stat.S_IFLNK >> 12:
                link = data.decode("utf-8", errors="replace").rstrip("\x00")
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                try:
                    os.symlink(link, dest)
                except FileExistsError:
                    pass
    # 数据目录（RPM 的 data/logs 等由安装脚本创建；这里补齐 plugins 等）
    for sub in ("data", "logs", "run", "import"):
        d = os.path.join(layout_home, sub)
        os.makedirs(d, exist_ok=True)
    print(f"RPM 解包完成 -> {layout_home}")


class _DecompReader:
    """把解压后的字节流包装成按需读取的文件对象（惰性解压，省内存）。"""

    def __init__(self, fp, decomp, offset, chunk_size):
        self.fp = fp
        self.decomp = decomp
        self.offset = offset
        self.chunk_size = chunk_size
        self.buf = b""
        self.eof = False
        self.pos = 0

    def read(self, n=-1):
        while not self.eof and (n < 0 or len(self.buf) < n):
            if self.eof:
                break
            raw = self.fp.read(self.chunk_size)
            if not raw:
                try:
                    tail = self.decomp.flush()
                except Exception:
                    tail = b""
                self.buf += tail
                self.eof = True
                break
            try:
                self.buf += self.decomp.decompress(raw)
            except (zlib.error, lzma.LZMAError) as e:
                if not self.buf:
                    raise
                self.eof = True
                break
        if n < 0:
            out, self.buf = self.buf, b""
        else:
            out, self.buf = self.buf[:n], self.buf[n:]
        self.pos += len(out)
        return out


def main() -> int:
    ap = argparse.ArgumentParser(description="解包 Neo4j RPM 为 tarball 布局")
    ap.add_argument("rpm_path")
    ap.add_argument("layout_home")
    args = ap.parse_args()
    extract(args.rpm_path, "", args.layout_home)
    return 0


if __name__ == "__main__":
    sys.exit(main())
