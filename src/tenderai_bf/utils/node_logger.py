"""Utility for logging node results to JSON files."""

import json
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

from ..logging import get_logger

logger = get_logger(__name__)

# Base directory for node output logs
NODE_LOGS_DIR = Path("/app/logs/nodes")

# Ensure directory exists
NODE_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def clear_node_output(node_name: str) -> None:
    """Clear the output JSON file for a specific node.
    
    Args:
        node_name: Name of the node (e.g., 'load_sources', 'fetch_listings')
    """
    output_file = NODE_LOGS_DIR / f"{node_name}.json"
    
    try:
        # Write empty array to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        
        logger.debug(f"Cleared output file for node: {node_name}", file=str(output_file))
        
    except Exception as e:
        logger.error(f"Failed to clear output file for node: {node_name}", error=str(e))


def log_node_output(
    node_name: str,
    data: Any,
    run_id: str = None,
    append: bool = False
) -> None:
    """Log node output to a JSON file.
    
    Args:
        node_name: Name of the node (e.g., 'load_sources', 'fetch_listings')
        data: Data to log (will be JSON serialized)
        run_id: Optional run ID for tracking
        append: If True, append to existing data; if False, overwrite
    """
    output_file = NODE_LOGS_DIR / f"{node_name}.json"
    
    try:
        # Prepare output structure
        output_entry = {
            '_logged_at': datetime.now().isoformat(),
            '_run_id': run_id,
            '_node': node_name,
            'data': data
        }
        
        if append and output_file.exists():
            # Read existing data
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                    if not isinstance(existing_data, list):
                        existing_data = [existing_data]
            except (json.JSONDecodeError, ValueError):
                existing_data = []
            
            # Append new entry
            existing_data.append(output_entry)
            output_data = existing_data
        else:
            # Single entry (wrapped in array for consistency)
            output_data = [output_entry]
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.info(
            f"Logged output for node: {node_name}",
            file=str(output_file),
            run_id=run_id,
            data_type=type(data).__name__
        )
        
    except Exception as e:
        logger.error(
            f"Failed to log output for node: {node_name}",
            error=str(e),
            run_id=run_id,
            exc_info=True
        )


def log_node_stats(
    node_name: str,
    stats: Dict[str, Any],
    run_id: str = None
) -> None:
    """Log node statistics/metrics.
    
    Args:
        node_name: Name of the node
        stats: Statistics dictionary
        run_id: Optional run ID for tracking
    """
    log_node_output(
        node_name=f"{node_name}_stats",
        data=stats,
        run_id=run_id,
        append=False
    )


def get_node_output_path(node_name: str) -> Path:
    """Get the path to a node's output file.
    
    Args:
        node_name: Name of the node
        
    Returns:
        Path to the output JSON file
    """
    return NODE_LOGS_DIR / f"{node_name}_output.json"
