#!/bin/bash
set -e

# Get the script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Load .env file if it exists (for development mode)
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "Loading .env file from $PROJECT_ROOT/.env"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Database connection details (can be overridden by environment variables)
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5432}
DB_USER=${DB_USER:-postgres}
DB_PASSWORD=${DB_PASSWORD:-postgres}
DB_NAME=${DB_NAME:-WeKnora}

# New migrations belong to the independent enterprise chain.
MIGRATIONS_DIR="migrations/enterprise/versioned"

case "$1" in
    up|down|goto|force|version)
        echo "Error: direct '$1' migration commands are disabled."
        echo "Use the canonical guarded application migration path instead:"
        echo "  Start WeKnora with AUTO_MIGRATE=true (the default)."
        exit 2
        ;;
esac

# Check if migrate tool is installed
if ! command -v migrate &> /dev/null; then
    echo "Error: migrate tool is not installed"
    echo "Install it with: go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest"
    exit 1
fi

# Construct the database URL
# If DB_URL is already set in .env, use it but ensure sslmode=disable is set
# Otherwise, construct it from individual components
if [ -n "$DB_URL" ]; then
    # If DB_URL already exists, ensure sslmode=disable is set (unless sslmode is already specified)
    if [[ "$DB_URL" != *"sslmode="* ]]; then
        # Add sslmode=disable if not present
        if [[ "$DB_URL" == *"?"* ]]; then
            DB_URL="${DB_URL}&sslmode=disable"
        else
            DB_URL="${DB_URL}?sslmode=disable"
        fi
    elif [[ "$DB_URL" == *"sslmode=require"* ]] || [[ "$DB_URL" == *"sslmode=prefer"* ]]; then
        # Replace sslmode=require/prefer with sslmode=disable for local dev
        DB_URL="${DB_URL//sslmode=require/sslmode=disable}"
        DB_URL="${DB_URL//sslmode=prefer/sslmode=disable}"
    fi
else
    # Use Python to properly URL encode password if it contains special characters
    # This handles special characters in passwords correctly
    if command -v python3 &> /dev/null; then
        ENCODED_PASSWORD=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$DB_PASSWORD', safe=''))")
    else
        # Fallback: try to use printf for basic encoding (may not work for all special chars)
        ENCODED_PASSWORD="$DB_PASSWORD"
    fi
    DB_URL="postgres://${DB_USER}:${ENCODED_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?sslmode=disable"
fi

# Execute migration based on command
case "$1" in
    create)
        if [ -z "$2" ]; then
            echo "Error: Migration name is required"
            echo "Usage: $0 create <migration_name>"
            exit 1
        fi
        echo "Creating migration files for $2..."
        migrate create -ext sql -dir ${MIGRATIONS_DIR} -seq $2
        echo "Created:"
        echo "  - ${MIGRATIONS_DIR}/$(ls -t ${MIGRATIONS_DIR} | head -1)"
        echo "  - ${MIGRATIONS_DIR}/$(ls -t ${MIGRATIONS_DIR} | head -2 | tail -1)"
        ;;
    *)
        echo "Usage: $0 create <migration_name>"
        echo "Database migration execution is handled by the guarded application startup path."
        exit 1
        ;;
esac

echo "Migration command completed successfully"
