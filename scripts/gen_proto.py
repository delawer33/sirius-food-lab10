"""
Генерация Python-кода из proto/delivery.proto в пакет delivery_grpc/.

    python -m scripts.gen_proto

protoc пишет в delivery_pb2_grpc.py абсолютный импорт `import delivery_pb2`.
Он работает, только если файл лежит в корне проекта, как в методичке. Здесь
код в пакете, поэтому импорт заменяется на относительный.
"""
import sys
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
PROTO_DIR = ROOT / "proto"
DEFAULT_OUT = ROOT / "delivery_grpc"


def generate(out: Path = DEFAULT_OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    code = protoc.main([
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        str(PROTO_DIR / "delivery.proto"),
    ])
    if code != 0:
        sys.exit(f"protoc завершился с кодом {code}")
    stub = out / "delivery_pb2_grpc.py"
    stub.write_text(stub.read_text().replace(
        "import delivery_pb2 as delivery__pb2", "from . import delivery_pb2 as delivery__pb2"
    ))


if __name__ == "__main__":
    generate()
    print(f"Сгенерировано в {DEFAULT_OUT}")
