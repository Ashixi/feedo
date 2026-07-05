use ed25519_dalek::{SigningKey, Signer};
use rand::rngs::OsRng;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::PathBuf;

pub struct UserIdentity {
    // Хранить приватний ключ, з якого за потреби автоматично виводиться публічний
    pub signing_key: SigningKey,
}

impl UserIdentity {
    /// Визначає шлях до прихованого файлу локального збереження ключа.
    fn get_storage_path() -> PathBuf {
        let mut path = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        path.push(".user_id.key");
        path
    }

    /// Основна логіка: завантажує ключ або створює новий, якщо це перший запуск.
    pub fn load_or_generate() -> Result<Self, String> {
        let path = Self::get_storage_path();

        if path.exists() {
            // --- КЛЮЧ ІСНУЄ: Завантажуємо його ---
            let mut file = File::open(&path)
                .map_err(|e| format!("Не вдалося відкрити файл ключа: {}", e))?;

            let mut key_bytes = [0u8; 32];
            file.read_exact(&mut key_bytes)
                .map_err(|e| format!("Помилка читання структури ключа: {}", e))?;

            let signing_key = SigningKey::from_bytes(&key_bytes);
            Ok(UserIdentity { signing_key })
        } else {
            // --- ПЕРШИЙ ЗАПУСК: Генеруємо нову пару ---
            let mut csprng = OsRng;
            let signing_key = SigningKey::generate(&mut csprng);
            let key_bytes = signing_key.to_bytes();

            // Створюємо файл для запису
            let mut file = File::create(&path)
                .map_err(|e| format!("Не вдалося створити файл ідентифікатора: {}", e))?;

            // Безпека ОС: на Unix обмежуємо доступ до файлу (тільки для власника програми)
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Ok(metadata) = file.metadata() {
                    let mut perms = metadata.permissions();
                    perms.set_mode(0o600); // -rw------- (тільки читання/запис власником)
                    let _ = file.set_permissions(perms);
                }
            }

            file.write_all(&key_bytes)
                .map_err(|e| format!("Не вдалося безпечно зберегти ключ: {}", e))?;

            println!("🔑 [Перший запуск]: Успішно згенеровано та захищено новий цифровий ID.");
            Ok(UserIdentity { signing_key })
        }
    }

    /// Повертає публічний ключ у вигляді Hex-рядка для відправки на сервер (ідентифікація)
    pub fn get_public_key_hex(&self) -> String {
        let verifying_key = self.signing_key.verifying_key();
        verifying_key
            .to_bytes()
            .iter()
            .map(|b| format!("{:02x}", b))
            .collect::<String>()
    }

    /// Підписує будь-які дані (наприклад, запис, токен або мережевий пакет) приватним ключем
    pub fn sign_payload(&self, message: &[u8]) -> std::vec::Vec<u8> {
        let signature = self.signing_key.sign(message);
        let sig_bytes = signature.to_bytes();
        sig_bytes.to_vec()
    }
}