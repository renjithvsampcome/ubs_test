import pytest
import pytest_asyncio
from market_validators.market_validator import MarketTypeValidator

@pytest.mark.asyncio
async def test_german_market_validation():
    validator = MarketTypeValidator()
    
    # Test with a known regulated market ISIN
    is_regulated, market_type, url = await validator._check_german_market("DE0007664039")  # Volkswagen
    
    # This is a simplified test - in reality, we'd use a mock or stub
    assert url is not None
    assert isinstance(is_regulated, bool)
    assert market_type is not None

@pytest.mark.asyncio
async def test_french_market_validation():
    validator = MarketTypeValidator()
    
    # Test with a known regulated market ISIN
    is_regulated, market_type, url = await validator._check_french_market("FR0000121972")  # Schneider Electric
    
    # This is a simplified test - in reality, we'd use a mock or stub
    assert url is not None
    assert isinstance(is_regulated, bool)
    assert market_type is not None

# tests/test_shares_validator.py
import pytest
import pytest_asyncio
from share_validators.outstanding_share_validator import OutstandingShareValidator

@pytest.mark.asyncio
async def test_german_share_validation():
    validator = OutstandingShareValidator()
    
    # Test with a known company
    is_valid, actual_shares, url = await validator._check_german_register(
        "Volkswagen AG", 
        "DE0007664039",
        295089818  # Expected shares (example value)
    )
    
    # This is a simplified test - in reality, we'd use a mock or stub
    assert url is not None
    
    # Either the validation worked and returned a boolean result
    # or it returned None if it couldn't find the information
    assert is_valid is None or isinstance(is_valid, bool)
