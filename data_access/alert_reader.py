import pandas as pd
import logging
from typing import List, Dict, Any
import os
from models.alert_models import Alert

logger = logging.getLogger(__name__)

def load_alerts_from_csv(file_path: str) -> List[Alert]:
    """
    Loads alerts from a CSV file
    
    Args:
        file_path: Path to the CSV file
        
    Returns:
        List of Alert objects
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"CSV file not found: {file_path}")
            return []
        
        df = pd.read_csv(file_path)
        
        # Check required columns
        required_columns = ['alert_id', 'isin', 'security_name']
        for col in required_columns:
            if col not in df.columns:
                logger.error(f"Required column '{col}' not found in CSV file")
                return []
        
        # Convert DataFrame to Alert objects
        alerts = []
        for _, row in df.iterrows():
            alert = Alert(
                alert_id=row['alert_id'],
                isin=row['isin'],
                security_name=row['security_name'],
                outstanding_shares_system=row.get('outstanding_shares_system')
            )
            alerts.append(alert)
        
        logger.info(f"Loaded {len(alerts)} alerts from CSV file")
        return alerts
    
    except Exception as e:
        logger.error(f"Error loading alerts from CSV: {e}", exc_info=True)
        return []

async def load_alerts_from_database(connection_string: str, query: str = None) -> List[Alert]:
    """
    Loads alerts from a database
    
    Args:
        connection_string: Database connection string
        query: Optional custom query to use
        
    Returns:
        List of Alert objects
    """
    try:
        import pyodbc
        
        # Connect to the database
        # In a real implementation, we would use an async database library
        conn = pyodbc.connect(connection_string)
        
        # Use default query if none provided
        if query is None:
            query = """
            SELECT 
                alert_id, 
                isin, 
                security_name, 
                outstanding_shares_system 
            FROM alerts 
            WHERE status = 'PENDING'
            """
        
        # Execute the query
        df = pd.read_sql(query, conn)
        
        # Close the connection
        conn.close()
        
        # Convert DataFrame to Alert objects
        alerts = []
        for _, row in df.iterrows():
            alert = Alert(
                alert_id=row['alert_id'],
                isin=row['isin'],
                security_name=row['security_name'],
                outstanding_shares_system=row.get('outstanding_shares_system')
            )
            alerts.append(alert)
        
        logger.info(f"Loaded {len(alerts)} alerts from database")
        return alerts
    
    except Exception as e:
        logger.error(f"Error loading alerts from database: {e}", exc_info=True)
        return []