# Firmware signing

Closes security finding **C3** (unsigned OTA / uploader-supplied checksums). Firmware
integrity is now established **server-side**, and, once devices ship the verifying
firmware, **end-to-end** with an offline signing key.

## Trust model

| Key | Where it lives | Role |
|-----|----------------|------|
| Ed25519 **private** key | Offline: a release manager's machine, or a CI secret. **Never on the server.** | Signs each firmware binary at release time. |
| Ed25519 **public** key | Server env `FIRMWARE_SIGNING_PUBKEY` **and** embedded in device firmware. | Verifies signatures. Public, so it is safe to commit / bake into firmware. |

Why it matters: an attacker who gains admin on the API (finding C1) still cannot ship
malicious firmware, because a valid signature requires the offline private key. Signing
is the control that **survives an admin compromise**; checksums alone do not.

## What changed on the server

- **Checksums are recomputed from the received bytes** on upload (`main.py`,
  `upload_firmware`). Any `sha256_checksum` / `md5_checksum` the uploader sends is now
  treated as an assertion to verify (mismatch → HTTP 400), never as the stored value.
  MD5 is retained only for backward compatibility with current devices; it is not a
  security control.
- **Signature verification** (`firmware_signing.py`): when `FIRMWARE_SIGNING_PUBKEY` is
  set, an upload must include a valid `signature` form field or it is rejected (400).
  The signature and its algorithm are stored (`firmware_versions.signature`,
  `signature_alg`) and served on `/api/ota/check` so devices can verify before flashing.
- **Graceful rollout:** with **no** public key configured, the server logs a loud
  warning and falls back to checksum-only (today's behaviour). This lets the code deploy
  before the key + CI signing are in place, without breaking the current release flow.

New columns are added by the existing idempotent `ALTER TABLE` migration block, so no
manual DB step.

## One-time setup

```bash
# 1. Generate the keypair (do this OFFLINE, once)
python firmware_signing.py keygen --out-dir ~/keys
#    -> ~/keys/firmware_signing_private.pem   (keep offline, back up securely)
#    -> prints  FIRMWARE_SIGNING_PUBKEY=<64 hex chars>

# 2. Configure the server (docker-compose env / secret), then restart
FIRMWARE_SIGNING_PUBKEY=<64 hex chars>

# 3. Add the private key PEM as a CI secret (e.g. FIRMWARE_SIGNING_KEY) in the
#    energy-pebble-esphome repo.
```

## Release pipeline (energy-pebble-esphome CI)

Add a signing step before the existing upload in `.github/workflows/build-firmware.yml`.
The server now recomputes checksums, so the sha256/md5 form fields become optional; the
**signature** is the field that matters:

```yaml
- name: Sign firmware
  run: |
    printf '%s' "${{ secrets.FIRMWARE_SIGNING_KEY }}" > /tmp/sign.pem
    SIG=$(python firmware_signing.py sign "$FIRMWARE_BIN" --key /tmp/sign.pem)
    echo "FIRMWARE_SIG=$SIG" >> "$GITHUB_ENV"
    rm -f /tmp/sign.pem
# then add  -F "signature=$FIRMWARE_SIG"  to the curl upload
```

(`firmware_signing.py` has no heavy deps beyond `cryptography`; copy it into the CI job
or install it from this repo.)

---

# Migrating the devices already in the wild (~20 units)

Fielded devices run firmware that does **not** verify signatures. The rollout must not
brick them. Two facts make this safe:

1. **Turning on server-side signing does not affect current devices.** The `signature`
   field in `/api/ota/check` is additive; today's firmware ignores unknown JSON keys and
   keeps updating exactly as before. So step 1 (enable signing on the server + start
   signing releases) is zero-risk for the fleet.
2. **The verifying firmware is delivered over the current (unverified) OTA path, once.**
   This is unavoidable chicken-and-egg: a device can only start checking signatures after
   it receives the firmware that knows how. That first hop is a **trust-on-first-update**;
   every update *after* it is cryptographically verified.

### ⚠️ Gate everything on the board-architecture question first

Before **any** OTA push, resolve the ESP32-**S3** vs Lolin-**C3** ambiguity (the build
dir contains both `energy-pebble` and `lolin-c3-led-ring` targets; finding in the device
review). Pushing a wrong-architecture binary **bricks** the device, a far bigger risk
than the signing change. Add a board/variant field to `/api/ota/check` matching and only
offer a binary built for the device's actual silicon.

### Sequence

1. **Server:** set `FIRMWARE_SIGNING_PUBKEY`, deploy this change. Fleet unaffected.
2. **Inventory the fleet:** confirm each device's board/arch and current version (the
   `devices` table + OTA logs). Do not proceed for a device whose arch is unknown.
3. **Release the first signature-capable firmware, signed,** built per-arch. It must:
   embed the public key, verify the served `signature` against the downloaded binary
   before flashing, and **fail closed** (refuse to flash on a bad/missing signature once
   this firmware is running).
4. **Staged OTA:** roll to 1–2 test devices first (ideally ones physically reachable in
   case of a bad flash), confirm they come back on the new version and report `completed`,
   then release to the rest. Keep `rollback_version` set so a failed flash reverts.
5. **After the fleet is on verifying firmware:** signing is end-to-end. Consider making
   the server reject **unsigned** firmware unconditionally (it already does when the key
   is set) and dropping MD5 from the device path.
6. **Later / hardware rev B:** for true anti-rollback and boot-level protection, enable
   ESP32 **Secure Boot v2 + flash encryption**. This is a one-way efuse operation done at
   manufacture, out of scope for the existing fleet, plan it for new production units.

### Rollback / safety net

- Devices that never check in for the new version stay on old firmware and keep working
  (degraded trust, but functional); no forced brick.
- Because the first update rides the old path, a device that is offline during the
  campaign simply picks it up whenever it next checks `/api/ota/check`.
- Pair this migration with the **stale-data indicator** fix (device review P0) so a device
  that goes quiet during a flash is visibly distinguishable from a working one.

## Tests

- `tests/test_firmware_signing.py`: unit tests for the sign/verify/keys module (offline).
- `tests/test_firmware_upload_signing.py`: integration tests: upload rejects unsigned /
  bad-signature / mismatched-checksum, stores the server-computed checksum, and
  `/api/ota/check` serves a signature that verifies against the served binary.

Run: `python tests/test_firmware_signing.py && python tests/test_firmware_upload_signing.py`
