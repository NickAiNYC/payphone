import os
import logging
from pathlib import Path
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class HermesSecureStorage:
    """Isolates key storage. Encrypts the agent's private key at rest using a local
    master key. In production, AGENT_MASTER_KEY comes from a secure vault/OS keyring.
    """

    def __init__(self, storage_path: str = "./keys/agent_keys.enc"):
        self.storage_path = Path(storage_path)
        master_key = os.environ.get("AGENT_MASTER_KEY")
        if not master_key:
            # Generate or reuse local key for development
            key_file = Path("./keys/.master_key")
            key_file.parent.mkdir(parents=True, exist_ok=True)
            if key_file.exists():
                master_key = key_file.read_bytes()
            else:
                master_key = Fernet.generate_key()
                key_file.write_bytes(master_key)
                os.chmod(key_file, 0o600)
        else:
            master_key = (
                master_key.encode("utf-8")
                if isinstance(master_key, str)
                else master_key
            )

        self.fernet = Fernet(master_key)

    def save_key(self, secret_hex: str):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = self.fernet.encrypt(secret_hex.encode("utf-8"))
        self.storage_path.write_bytes(encrypted)
        os.chmod(self.storage_path, 0o600)

    def load_key(self) -> str:
        if self.storage_path.exists():
            encrypted = self.storage_path.read_bytes()
            return self.fernet.decrypt(encrypted).decode("utf-8")
        else:
            # Generate new key hex if absent
            import secrets

            secret_hex = secrets.token_hex(32)
            self.save_key(secret_hex)
            logger.info(f"[SecureStorage] Generated new encrypted agent key at rest.")
            return secret_hex
