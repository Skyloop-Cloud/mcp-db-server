"""
FastAPI MCP Database Server

An MCP server that exposes relational databases to AI agents with natural language query support.
"""

import os
import sys
import logging
from typing import Dict, List, Any, Optional
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from .db import DatabaseManager, get_db_manager
    from .nl_to_sql import NLToSQLConverter
except ImportError:
    # Fallback for direct execution
    sys.path.insert(0, os.path.dirname(__file__))
    from db import DatabaseManager, get_db_manager
    from nl_to_sql import NLToSQLConverter

# Import FastMCP instance from mcp_server.py for MCP protocol endpoints
try:
    # Add parent directory to path to import mcp_server
    parent_dir = Path(__file__).parent.parent
    if str(parent_dir) not in sys.path:
        sys.path.insert(0, str(parent_dir))
    
    # Import the FastMCP instance and initialization function
    from mcp_server import mcp, initialize_database
    MCP_AVAILABLE = True
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"FastMCP not available: {e}. MCP protocol endpoints (/mcp, /sse) will not be available.")
    MCP_AVAILABLE = False
    mcp = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models for request/response
class QueryRequest(BaseModel):
    nl_query: str
    limit: Optional[int] = 50

class QueryResponse(BaseModel):
    sql_query: str
    results: List[Dict[str, Any]]
    row_count: int

class TableInfo(BaseModel):
    table_name: str
    column_count: int

class ColumnInfo(BaseModel):
    column_name: str
    data_type: str
    is_nullable: bool

class TableSchema(BaseModel):
    table_name: str
    columns: List[ColumnInfo]

# Global variables
nl_converter: Optional[NLToSQLConverter] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global nl_converter
    
    # Startup
    logger.info("Starting MCP Database Server...")
    try:
        nl_converter = NLToSQLConverter()
        logger.info("NL to SQL converter initialized")
    except Exception as e:
        logger.error(f"Failed to initialize NL converter: {e}")
        nl_converter = None
    
    # Initialize FastMCP database connection if available
    if MCP_AVAILABLE and mcp is not None:
        try:
            await initialize_database()
            logger.info("FastMCP database initialized for MCP protocol endpoints")
        except Exception as e:
            logger.warning(f"Failed to initialize FastMCP database: {e}. MCP endpoints may not work correctly.")
    
    yield
    
    # Shutdown
    logger.info("Shutting down MCP Database Server...")

# Create FastAPI app
app = FastAPI(
    title="MCP Database Server",
    description="An MCP server exposing relational databases (Postgres/MySQL) to AI agents. Supports NL→SQL.",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount FastMCP HTTP endpoints for MCP protocol support (/mcp and /sse)
if MCP_AVAILABLE and mcp is not None:
    try:
        # Mount streamable HTTP app at /mcp
        mcp_http_app = mcp.streamable_http_app()
        app.mount("/mcp", mcp_http_app)
        logger.info("Mounted FastMCP streamable HTTP endpoint at /mcp")
        
        # Mount SSE app at /sse
        mcp_sse_app = mcp.sse_app()
        app.mount("/sse", mcp_sse_app)
        logger.info("Mounted FastMCP SSE endpoint at /sse")
    except Exception as e:
        logger.error(f"Failed to mount FastMCP endpoints: {e}")
        logger.warning("MCP protocol endpoints (/mcp, /sse) will not be available")
else:
    logger.warning("FastMCP not available. MCP protocol endpoints (/mcp, /sse) will not be available")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "mcp-db-server",
        "version": "1.1.0",
        "database_connected": True  # Will be updated with actual DB check
    }

@app.get("/mcp/list_tables", response_model=List[TableInfo])
async def list_tables(db_manager: DatabaseManager = Depends(get_db_manager)):
    """List all available tables in the database"""
    try:
        tables = await db_manager.list_tables()
        return [
            TableInfo(
                table_name=table["table_name"],
                column_count=table["column_count"]
            )
            for table in tables
        ]
    except Exception as e:
        logger.error(f"Error listing tables: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list tables: {str(e)}")

@app.get("/mcp/describe/{table_name}", response_model=TableSchema)
async def describe_table(table_name: str, db_manager: DatabaseManager = Depends(get_db_manager)):
    """Get schema information for a specific table"""
    try:
        schema = await db_manager.describe_table(table_name)
        return TableSchema(
            table_name=table_name,
            columns=[
                ColumnInfo(
                    column_name=col["column_name"],
                    data_type=col["data_type"],
                    is_nullable=col["is_nullable"]
                )
                for col in schema
            ]
        )
    except Exception as e:
        logger.error(f"Error describing table {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to describe table: {str(e)}")

@app.post("/mcp/query", response_model=QueryResponse)
async def execute_nl_query(
    request: QueryRequest,
    db_manager: DatabaseManager = Depends(get_db_manager)
):
    """Convert natural language query to SQL and execute it"""
    global nl_converter
    
    if not nl_converter:
        raise HTTPException(status_code=503, detail="NL to SQL converter not available")
    
    try:
        # Get table schemas for context
        tables = await db_manager.list_tables()
        table_schemas = {}
        for table in tables:
            schema = await db_manager.describe_table(table["table_name"])
            table_schemas[table["table_name"]] = schema
        
        # Convert natural language to SQL
        sql_query = nl_converter.convert_to_sql(request.nl_query, table_schemas)
        
        # Execute the query with safety checks
        results = await db_manager.execute_safe_query(sql_query, limit=request.limit)
        
        return QueryResponse(
            sql_query=sql_query,
            results=results,
            row_count=len(results)
        )
        
    except Exception as e:
        logger.error(f"Error executing NL query '{request.nl_query}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to execute query: {str(e)}")

@app.get("/mcp/tables/{table_name}/sample")
async def get_table_sample(
    table_name: str,
    limit: int = 5,
    db_manager: DatabaseManager = Depends(get_db_manager)
):
    """Get a sample of data from a specific table"""
    try:
        query = f"SELECT * FROM {table_name} LIMIT {min(limit, 50)}"
        results = await db_manager.execute_safe_query(query, limit=min(limit, 50))
        
        return {
            "table_name": table_name,
            "sample_data": results,
            "row_count": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error getting sample from table {table_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get table sample: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "app.server:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )