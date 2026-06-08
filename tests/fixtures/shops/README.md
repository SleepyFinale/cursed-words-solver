# Shop fixture capture

1. Rebuild melmod: `.\melmod\build.ps1`
2. Enter the Ej?A56 shop in-game and press **F7**
3. Copy `%USERPROFILE%\.cursed_words_solver\run_state.json` here as `YYYYMMDD_<character>_shop.json`
4. Run `pytest tests/integration/test_shop_parse.py -q` to verify the `shop` block parses
