# Corvusforge Quickstart

**Version:** 0.4.0

## Installation

### From Source (Development)

```bash
git clone https://github.com/nikodemus-eth/corvusforge.git
cd corvusforge
pip install -e ".[dev]"
```

### From PyPI

```bash
pip install corvusforge==0.4.0
```

### Verify Installation

```bash
corvusforge --help
python -c "import corvusforge; print(corvusforge.__version__)"
```

### Verify Crypto

```bash
python -c "
from corvusforge.bridge.crypto_bridge import *
priv, pub = generate_keypair()
sig = sign_data(b'hello corvusforge', priv)
print('Crypto OK:', verify_data(b'hello corvusforge', sig, pub))
"
```

Expected output: `Crypto OK: True`

## First Run

### End-to-End Demo

```bash
corvusforge demo
```

Runs the full 10-stage pipeline with default configuration. Prints Rich-formatted output showing each stage transition, hash chain verification, and trust context.

### Create a New Pipeline Run

```bash
corvusforge new
```

Starts a fresh pipeline run with an auto-generated run ID.

### Monitor Pipeline State

```bash
corvusforge monitor
```

Displays the Rich terminal Build Monitor showing stage states, hash chain status, and trust health.

### Check SAOE Integration Status

```bash
corvusforge saoe-status
```

Shows which SAOE components are available (crypto, transport, agents, audit).

## Streamlit Dashboard

```bash
corvusforge ui
```

Launches the Build Monitor 2.0 Streamlit dashboard at `http://localhost:8501`. Features:

- Live pipeline state visualization
- Run history browser
- Hash chain verification
- Trust context inspector
- Fleet telemetry

## Working with Plugins

### List Installed Plugins

```bash
corvusforge plugins
```

### DLC Package Structure

```
my-plugin-1.0.0/
    manifest.json      # Plugin metadata
    plugin.py          # Implementation
    signature.sig      # Ed25519 signature
```

### Marketplace Operations

```python
from corvusforge.marketplace.marketplace import Marketplace
from pathlib import Path

mp = Marketplace(
    marketplace_dir=Path(".corvusforge/marketplace/"),
    verification_public_key="<your-trust-root-public-key>",
)

# Publish
listing = mp.publish(Path("my-plugin-1.0.0"), author="Your Name")

# Search
results = mp.search(query="slack")

# Verify signature
verified = mp.verify_listing("my-plugin")

# Install
entry = mp.install("my-plugin")
```

## Docker Deployment

### Build

```bash
docker build -t corvusforge:0.4.0 .
```

### Run

```bash
# Dashboard (default)
docker run -p 8501:8501 corvusforge:0.4.0

# Demo
docker run corvusforge:0.4.0 corvusforge demo
```

### Docker Compose

```bash
docker-compose up --build
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CORVUSFORGE_ENVIRONMENT` | `production` | Environment mode |
| `CORVUSFORGE_DOCKER_MODE` | `true` | Docker detection |
| `CORVUSFORGE_LEDGER_PATH` | `.corvusforge/ledger.db` | Ledger database |
| `CORVUSFORGE_THINGSTEAD_DATA` | `.openclaw-data` | Fleet memory |

## Running Tests

```bash
# Full suite (387 tests)
pytest

# Quick summary
pytest --tb=short -q

# Unit tests only
pytest tests/unit/

# Adversarial tests only
pytest tests/adversarial/

# With coverage
pytest --cov=corvusforge --cov-report=html
```

## Python API

### Minimal Pipeline Run

```python
from corvusforge.core.orchestrator import Orchestrator
from corvusforge.config import ProdConfig

# Initialize (debug mode — no trust root keys required)
orch = Orchestrator(prod_config=ProdConfig(environment="debug"))

# Start a run
run_config = orch.start_run()

# Execute stages
for stage_id in ["s1_prerequisites", "s2_environment", "s3_test_contracting"]:
    result = orch.execute_stage(stage_id)
    print(f"{stage_id}: {result['status']}")

# Verify integrity
assert orch.verify_chain()
print(f"Run {orch.run_id}: chain valid")
```

### Custom Stage Handler

```python
def my_handler(run_id: str, payload: dict) -> dict:
    # Your stage logic here
    return {"status": "passed", "output": "done"}

orch.register_stage_handler("s5_implementation", my_handler)
result = orch.execute_stage("s5_implementation", payload={"spec": "..."})
```

### Fleet Execution

```python
from corvusforge.thingstead.fleet import ThingsteadFleet, FleetConfig

fleet = ThingsteadFleet(config=FleetConfig(fleet_name="dev", max_agents=4))
result = fleet.execute_stage("s5_implementation", payload={"task": "build"})
print(f"Agent {result['agent_id']} completed in {result['receipt']['duration_ms']}ms")
fleet.shutdown()
```

## Next Steps

- Read [Architecture](architecture.md) for system design details
- Read [API Reference](api-reference.md) for complete interface documentation
- Review [Hardening Log](hardening-log.md) for security audit history
- Check [ADRs](adr/) for architectural decision records
