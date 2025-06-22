# Sports Connect Automation

A robust automation framework for Sports Connect/Blue Sombrero report exports.

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd SportsConnectAutomation
   ```

2. **Set up Python virtual environment**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   # or
   source venv/bin/activate  # Linux/Mac
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the application**
   - Copy `config/config.example.json` to `config/config.json`
   - Update settings in `config/config.json`
   - Run setup script: `python scripts/setup.py`

5. **Run the automation**
   ```bash
   python src/main.py
   ```

## Project Structure

```
SportsConnectAutomation/
├── src/                    # Source code
│   ├── core/              # Core framework modules
│   ├── automation/        # Automation logic
│   ├── integrations/      # External integrations
│   └── utilities/         # Utility functions
├── tests/                 # Test suite
├── config/                # Configuration files
├── data/                  # Data storage
├── logs/                  # Log files
├── docs/                  # Documentation
└── scripts/               # Utility scripts
```

## Development

### Running Tests
```bash
pytest tests/
```

### Code Formatting
```bash
black src/
```

### Linting
```bash
flake8 src/
pylint src/
```

## Visual Studio Setup

1. Open `SportsConnectAutomation.sln` in Visual Studio
2. Set Python interpreter to your virtual environment
3. Use F5 to run with debugging

## License

Copyright (c) 2024 - All rights reserved.
