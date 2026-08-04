import faiss
import os


def build_index(features, index_path):
    index = faiss.IndexFlatIP(features.shape[1])
    index.add(features)
    faiss.write_index(index, index_path)
    print(f"索引已重建并保存至: {index_path}")
    return index


def load_index(index_path):
    if os.path.exists(index_path):
        print("加载已有索引...")
        index = faiss.read_index(index_path)
        return index
    else:
        print("索引文件不存在")
        return None
