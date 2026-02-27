# Corvusforge Operational Runbook

**Version:** 1.0
**Date:** 2026-02-26

---

## 1. Enable Strict Waiver Verification in Production

### When

Before any production deployment. Strict mode must be active whenever `CORVUSFORGE_ENVIRONMENT=production`.

### How

Set the environment variable:

```bash
export CORVUSFORGE_ENVIRONMENT=production
```

The production config guard (`corvusforge/core/production_guard.py`) enforces that `require_signature=True` when the environment is `production`. The `Orchestrator` passes this flag to `WaiverManager` automatically based on `ProdConfig.is_production`.

### Verify

```bash
python -c "
from corvusforge.config import config
print(f'Environment: {config.environment}')
print(f'Is production: {config.is_production}')
"
```

In production, any attempt to register an unsigned waiver will raise `WaiverSignatureError`.

### If It Fails

If waivers cannot be registered because signing infrastructure is unavailable:
1. Do NOT downgrade to `CORVUSFORGE_ENVIRONMENT=development`. This disables all production guards.
2. Fix the signing infrastructure. Waivers bypass safety gates — they must be signed.
3. If the gate itself is the problem (false positive), file an issue and fix the gate. Do not waive it without a signature.

---

## 2. Rotate Signing Keys

### Plugin Signing Keys

1. Generate a new Ed25519 key pair via saoe-core:
   ```bash
   saoe keygen --type ed25519 --output new-plugin-key
   ```
2. Re-sign all active plugins with the new key:
   ```bash
   saoe sign --key new-plugin-key.priv --input <plugin-package>
   ```
3. Re-verify all plugins through the registry:
   ```python
   from corvusforge.plugins.registry import PluginRegistry
   registry = PluginRegistry(Path(".corvusforge/plugins"))
   for name in registry.list_plugins():
       result = registry.verify_plugin(name)
       print(f"{name}: verified={result}")
   ```
4. Revoke the old key by removing it from any trusted key stores.
5. Update CI secrets with the new key.

### Waiver Signing Keys

1. Generate a new key pair for the approving identity.
2. Existing waivers signed with the old key remain valid until expiration (waivers are immutable once stored).
3. New waivers must be signed with the new key.
4. The old key should be decommissioned after all waivers signed with it have expired.

### Emergency Key Rotation

If a signing key is compromised:
1. Immediately revoke the key from all CI secrets and keystores.
2. Audit the ledger for any waivers or plugins signed with the compromised key.
3. Re-verify all plugins. Any that were signed with the compromised key must be re-signed with a new key or removed.
4. Any active waivers signed with the compromised key should be treated as potentially forged. Review their justifications manually.

---

## 3. Revoke a Plugin

### Disable a Plugin

```python
from corvusforge.plugins.registry import PluginRegistry
registry = PluginRegistry(Path(".corvusforge/plugins"))
registry.disable_plugin("plugin-name")
```

This sets `enabled=False` in the registry. The plugin remains installed but will not be loaded or executed.

### Remove a Plugin Entirely

```python
registry.uninstall_plugin("plugin-name")
```

This removes the plugin entry from the registry and deletes the package files.

### Revoke Trust for a Plugin

If a plugin is found to be malicious:
1. Disable it immediately (see above).
2. Record the revocation in the ledger:
   ```python
   from corvusforge.core.run_ledger import RunLedger
   ledger = RunLedger(Path(".corvusforge/ledger.db"))
   ledger.append(
       run_id="system",
       stage_id="plugin_revocation",
       payload={"plugin": "plugin-name", "reason": "malicious", "timestamp": "..."},
   )
   ```
3. Audit all runs that used the plugin. Check ledger entries for stage outputs produced while the plugin was active.
4. If the plugin was a `stage_extension`, re-run affected stages without it and compare outputs.

---

## 4. Export and Store Ledger Anchors

### When to Export

Export an anchor at the end of every pipeline run, before the release stage (s7) completes. The production config guard enforces this.

### How to Export

```python
from corvusforge.core.run_ledger import RunLedger
import json

ledger = RunLedger(Path(".corvusforge/ledger.db"))
anchor = ledger.export_anchor(run_id="cf-20260226-143000-a1b")
print(json.dumps(anchor, indent=2))
```

### Where to Store Anchors

Anchors must be stored **outside the ledger's trust domain** (see threat model, Tier 1):

| Storage Location | Trust Level | Notes |
|-----------------|------------|-------|
| Same filesystem | Low | Attacker with file write can rewrite both |
| Separate S3 bucket (different credentials) | Medium | Requires separate compromise |
| Transparency log (e.g., Sigstore Rekor) | High | Public, append-only, independently verifiable |
| Email to distribution list | Medium | Timestamped, hard to retroactively modify |
| Git tag in separate repository | Medium | Requires separate push access |

**Hard requirement:** Anchor storage must use **different credentials** than the project directory. If the same credentials (SSH key, IAM role, access token) can write both the ledger and the anchor, anchor verification provides zero additional security over the hash chain alone.

Recommended minimum: Separate S3 bucket with a different IAM role, or a git tag in a repository that the CI pipeline's credentials cannot push to.

**Anti-pattern:** Storing anchors in `.corvusforge/anchors/` within the project directory. This is symbolic anchoring — an attacker with file write access can rewrite both the ledger and the anchors atomically.

### How to Verify Against an Anchor

```python
import json

# Load the previously exported anchor
with open("anchors/cf-20260226-143000-a1b.json") as f:
    anchor = json.load(f)

# Verify current ledger state against anchor
ledger = RunLedger(Path(".corvusforge/ledger.db"))
try:
    ledger.verify_against_anchor("cf-20260226-143000-a1b", anchor)
    print("Ledger matches anchor.")
except LedgerIntegrityError as e:
    print(f"INTEGRITY VIOLATION: {e}")
```

---

## 5. Restore from Backup

### Ledger Database

The ledger is a SQLite database at `.corvusforge/ledger.db`. To restore:

1. Stop any running Corvusforge processes.
2. Copy the backup ledger to `.corvusforge/ledger.db`.
3. Verify chain integrity:
   ```python
   ledger = RunLedger(Path(".corvusforge/ledger.db"))
   for run_id in ledger.list_runs():
       ledger.verify_chain(run_id)
       print(f"Run {run_id}: chain valid")
   ```
4. If you have anchors, verify against them:
   ```python
   ledger.verify_against_anchor(run_id, anchor)
   ```
5. If chain verification fails, the backup is corrupted. Do not use it.

### Artifact Store

Artifacts are stored as content-addressed files in `.corvusforge/artifacts/`. Each file is named by its SHA-256 hash. To verify integrity:

```python
from corvusforge.core.artifact_store import ContentAddressedStore
store = ContentAddressedStore(Path(".corvusforge/artifacts"))
# Re-hash every artifact and compare to filename
for artifact in store.list_artifacts():
    store.verify(artifact.content_address)
```

If any artifact's content doesn't match its hash key, the store is corrupted.

### Plugin Registry

The plugin registry is `.corvusforge/plugins/registry.json`. After restoring:

1. Re-verify all plugins:
   ```python
   registry = PluginRegistry(Path(".corvusforge/plugins"))
   for name in registry.list_plugins():
       registry.verify_plugin(name)
   ```
2. Any plugin that fails verification should be disabled until re-signed.

---

## 6. Respond to Monitor Alerts

### "Chain Broken" or "Integrity Violation"

The Build Monitor shows this when `verify_chain()` detects a hash chain inconsistency.

**Immediate actions:**
1. Stop the current run. Do not proceed past the current stage.
2. Export the current ledger state for forensic analysis.
3. Check for recent filesystem modifications (was the SQLite file edited externally?).
4. Verify against the most recent external anchor.
5. If the anchor matches, the violation occurred after the anchor was taken — scope the damage window.
6. If the anchor doesn't match, the violation may predate the anchor — wider investigation needed.

**Do NOT:**
- Re-run `verify_chain()` hoping it passes. If the chain is broken, it stays broken.
- Delete the corrupted ledger. Preserve it for forensic analysis.
- Continue the pipeline run. A broken chain means the integrity guarantee is void.

### "Blocked" Stage

A stage shows as BLOCKED when its prerequisites have not been met (prerequisite stages not PASSED).

**Check:**
1. Which prerequisite failed? Run `stage_machine.get_prerequisites(stage_id)`.
2. Was the prerequisite waived? Check `waiver_manager.has_valid_waiver(scope)`.
3. If the prerequisite failed legitimately, fix the issue in the failing stage and re-run it.
4. If a waiver is needed, create a signed waiver (production) or unsigned waiver (development).

### "Drift Detected"

If the monitor shows unexpected state changes between refreshes, this suggests concurrent modification of the ledger.

**Check:**
1. Is another Corvusforge process running against the same ledger? Corvusforge is single-writer.
2. Is a CI job and a local process both writing to the same ledger file?
3. Use `fuser` or `lsof` to check what processes have the SQLite file open.

---

## 7. Production Deployment Checklist

Before deploying Corvusforge to a production environment:

- [ ] `CORVUSFORGE_ENVIRONMENT=production` is set
- [ ] Signing keys are provisioned for waiver approvers
- [ ] Plugin signing keys are provisioned and stored securely
- [ ] Anchor storage location is configured (external to project directory)
- [ ] Anchor export is integrated into the release stage (s7)
- [ ] All plugins are re-verified after deployment
- [ ] Build Monitor is accessible to operators
- [ ] Backup schedule is configured for ledger and artifact store
- [ ] Key rotation schedule is documented
- [ ] This runbook is accessible to all operators
