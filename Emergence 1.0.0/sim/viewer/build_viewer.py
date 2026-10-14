"""Inline viewer data into the standalone viewer page.

  python3 viewer/build_viewer.py out/viewer_seed7.json out/chronique.html
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def build(data_path, out_path):
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    with open(data_path, encoding="utf-8") as f:
        data = f.read()
    data = data.replace("</", "<\\/")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__DATA__", data))
    return out_path


if __name__ == "__main__":
    print(build(sys.argv[1], sys.argv[2]))
