"""Load and validate active sources for the pipeline."""

import time
from datetime import datetime
from typing import Dict, List

from ...config import settings
from ...db import get_db_context
from ...logging import get_logger
from ...models import Source

logger = get_logger(__name__)


def load_sources_node(state) -> Dict:
    """Load active sources from configuration and database."""
    
    logger.info("Starting load_sources step", run_id=state.run_id)
    start_time = time.time()
    
    try:
        sources = []
        
        # If sources are already provided in state, use them
        if state.sources:
            logger.info(
                "Using sources from state",
                count=len(state.sources),
                run_id=state.run_id
            )
            state.update_stats(sources_checked=len(state.sources))
            return state
        
        # Load from configuration
        config_sources = settings.get_active_sources()
        logger.info(
            "Loaded sources from configuration",
            count=len(config_sources),
            run_id=state.run_id
        )
        
        # Validate and enrich sources from database
        with get_db_context() as session:
            for config_source in config_sources:
                source_name = config_source.get('name', 'Unknown')
                
                try:
                    # Find or create source in database
                    db_source = session.query(Source).filter(
                        Source.name == source_name
                    ).first()
                    
                    if not db_source:
                        # Create new source
                        db_source = Source(
                            name=source_name,
                            base_url=config_source.get('base_url', ''),
                            list_url=config_source.get('list_url', ''),
                            parser_type=config_source.get('parser', 'html'),
                            rate_limit=config_source.get('rate_limit', '10/m'),
                            enabled=config_source.get('enabled', True),
                            patterns=config_source.get('patterns', {})
                        )
                        session.add(db_source)
                        session.commit()
                        logger.info(
                            "Created new source",
                            source_name=source_name,
                            run_id=state.run_id
                        )
                    else:
                        # Update existing source with config
                        db_source.base_url = config_source.get('base_url', db_source.base_url)
                        db_source.list_url = config_source.get('list_url', db_source.list_url)
                        db_source.parser_type = config_source.get('parser', db_source.parser_type)
                        db_source.rate_limit = config_source.get('rate_limit', db_source.rate_limit)
                        db_source.enabled = config_source.get('enabled', db_source.enabled)
                        if 'patterns' in config_source:
                            db_source.patterns = config_source['patterns']
                        db_source.updated_at = datetime.utcnow()
                        session.commit()
                    
                    # Only include enabled sources
                    if db_source.enabled:
                        source_data = {
                            'id': db_source.id,
                            'name': db_source.name,
                            'base_url': db_source.base_url,
                            'list_url': db_source.list_url,
                            'parser_type': db_source.parser_type,
                            'rate_limit': db_source.rate_limit,
                            'patterns': db_source.patterns or {},
                            'last_seen_at': db_source.last_seen_at.isoformat() if db_source.last_seen_at else None,
                            'last_success_at': db_source.last_success_at.isoformat() if db_source.last_success_at else None,
                            'last_error_at': db_source.last_error_at.isoformat() if db_source.last_error_at else None,
                            'last_error_message': db_source.last_error_message
                        }
                        sources.append(source_data)
                        
                        logger.debug(
                            "Source loaded",
                            source_name=source_name,
                            enabled=db_source.enabled,
                            run_id=state.run_id
                        )
                    else:
                        logger.info(
                            "Source disabled, skipping",
                            source_name=source_name,
                            run_id=state.run_id
                        )
                
                except Exception as e:
                    logger.error(
                        "Failed to process source",
                        source_name=source_name,
                        error=str(e),
                        run_id=state.run_id
                    )
                    state.add_error(
                        "load_sources",
                        f"Failed to process source {source_name}: {str(e)}",
                        source_name=source_name
                    )
        
        # Update state
        state.sources = sources
        state.update_stats(sources_checked=len(sources))
        
        # Log completion
        duration = time.time() - start_time
        logger.info(
            "Load sources completed",
            sources_loaded=len(sources),
            duration_seconds=duration,
            run_id=state.run_id
        )
        
        # If no sources found, this is an error condition
        if not sources:
            state.add_error(
                "load_sources",
                "No active sources found to monitor",
                config_sources_count=len(config_sources)
            )
            state.should_continue = False
        
        return state
    
    except Exception as e:
        logger.error(
            "Load sources step failed",
            error=str(e),
            run_id=state.run_id,
            exc_info=True
        )
        state.add_error("load_sources", str(e))
        state.should_continue = False
        return state