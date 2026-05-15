// static/js/crypto.js
// Chiffrement réel AES-256-GCM

class CryptoService {
    constructor() {
        this.algorithm = 'AES-GCM';
        this.keyLength = 256;
        this.ivLength = 12;
    }

    // Générer une clé AES-256
    async generateKey() {
        return await crypto.subtle.generateKey(
            {
                name: this.algorithm,
                length: this.keyLength
            },
            true,
            ['encrypt', 'decrypt']
        );
    }

    // Exporter la clé en format WebCrypto
    async exportKey(key) {
        return await crypto.subtle.exportKey('jwk', key);
    }

    // Importer une clé
    async importKey(jwk) {
        return await crypto.subtle.importKey(
            'jwk',
            jwk,
            { name: this.algorithm },
            true,
            ['encrypt', 'decrypt']
        );
    }

    // Chiffrer un fichier
    async encryptFile(file, key = null) {
        const encryptionKey = key || await this.generateKey();
        const iv = crypto.getRandomValues(new Uint8Array(this.ivLength));
        
        // Lire le fichier
        const fileData = await this.readFile(file);
        
        // Chiffrer les données
        const encryptedData = await crypto.subtle.encrypt(
            {
                name: this.algorithm,
                iv: iv,
                tagLength: 128
            },
            encryptionKey,
            fileData
        );
        
        // Créer l'en-tête de chiffrement
        const header = new Uint8Array([
            ...iv,
            ...new Uint8Array(encryptedData)
        ]);
        
        return {
            encrypted: header,
            key: await this.exportKey(encryptionKey),
            iv: Array.from(iv),
            algorithm: this.algorithm,
            keyLength: this.keyLength
        };
    }

    // Déchiffrer un fichier
    async decryptFile(encryptedData, keyJwk, iv) {
        const key = await this.importKey(keyJwk);
        const decrypted = await crypto.subtle.decrypt(
            {
                name: this.algorithm,
                iv: new Uint8Array(iv),
                tagLength: 128
            },
            key,
            encryptedData
        );
        
        return decrypted;
    }

    // Lire un fichier en ArrayBuffer
    readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = (e) => resolve(e.target.result);
            reader.onerror = reject;
            reader.readAsArrayBuffer(file);
        });
    }

    // Convertir ArrayBuffer en Blob
    arrayBufferToBlob(buffer, mimeType) {
        return new Blob([buffer], { type: mimeType });
    }
}

window.cryptoService = new CryptoService();