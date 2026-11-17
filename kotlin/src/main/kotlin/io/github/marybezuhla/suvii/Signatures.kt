// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import java.util.Base64

/**
 * Ed25519 signatures. Uses BouncyCastle because Android 12 has no built-in Ed25519; on any
 * Android version the result is the same.
 */
object Signatures {
    private fun decode(text: String, size: Int): ByteArray? =
        try {
            Base64.getDecoder().decode(text.trim()).takeIf { it.size == size }
        } catch (e: IllegalArgumentException) {
            null
        }

    /** True if [signature] (base64) over [message] was made by one of [trustedKeys] (base64). */
    fun verify(trustedKeys: List<String>, signature: String, message: ByteArray): Boolean {
        val sig = decode(signature, 64) ?: return false
        for (key in trustedKeys) {
            val raw = decode(key, 32) ?: continue
            val valid = try {
                Ed25519Signer().run {
                    init(false, Ed25519PublicKeyParameters(raw, 0))
                    update(message, 0, message.size)
                    verifySignature(sig)
                }
            } catch (e: IllegalArgumentException) {
                false // not a point on the curve: no signature can be valid for it
            }
            if (valid) return true
        }
        return false
    }
}
