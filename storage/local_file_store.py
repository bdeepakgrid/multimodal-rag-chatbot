from pathlib import Path

from config.settings import Settings


class LocalFileStore:
    def __init__(self, settings: Settings):
        self.base_dir = settings.upload_path

    def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        tenant_dir = self.base_dir / tenant_id
        tenant_dir.mkdir(parents=True, exist_ok=True)
        dest = tenant_dir / filename
        dest.write_bytes(content)
        return str(dest.resolve())

    def save_from_path(self, tenant_id: str, source_path: Path) -> str:
        content = source_path.read_bytes()
        return self.save(tenant_id, source_path.name, content)

    def delete(self, tenant_id: str, filename: str) -> bool:
        path = self.base_dir / tenant_id / filename
        if path.exists():
            path.unlink()
            return True
        return False

    def get_path(self, tenant_id: str, filename: str) -> Path:
        return self.base_dir / tenant_id / filename
