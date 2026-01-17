#!/bin/bash
# HITL Service Deployment Script
# Usage: ./deploy.sh [forward|hil|all]
# Default: all (deploy all services)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Ensure uv is in PATH
export PATH="/root/.local/bin:$PATH"

# Pull latest code
pull_code() {
    log_info "Pulling latest code..."
    git pull origin main
}

# Deploy Forward Service
deploy_forward() {
    log_info "========== Deploying Forward Service =========="
    cd "$PROJECT_DIR/packages/forward-service"
    
    log_info "Syncing dependencies..."
    uv sync
    
    log_info "Running database migrations..."
    uv run alembic upgrade head || log_warn "Migration failed or not needed"
    
    log_info "Restarting Forward Service..."
    sudo systemctl restart forward-service
    
    sleep 2
    if systemctl is-active --quiet forward-service; then
        log_info "Forward Service started successfully"
    else
        log_error "Forward Service failed to start"
        sudo systemctl status forward-service --no-pager
        return 1
    fi
}

# Deploy HIL Service
deploy_hil() {
    log_info "========== Deploying HIL Service =========="
    cd "$PROJECT_DIR/packages/hil-server"
    
    log_info "Syncing dependencies..."
    uv sync
    
    # Ensure fly-pigeon is installed
    uv pip install fly-pigeon 2>/dev/null || true
    
    log_info "Running database migrations..."
    uv run alembic upgrade head || log_warn "Migration failed or not needed"
    
    log_info "Restarting HIL Service..."
    sudo systemctl restart hil-service
    
    sleep 2
    if systemctl is-active --quiet hil-service; then
        log_info "HIL Service started successfully"
    else
        log_error "HIL Service failed to start"
        sudo systemctl status hil-service --no-pager
        return 1
    fi
}

# Check service status
check_status() {
    log_info "========== Service Status =========="
    echo ""
    sudo systemctl status forward-service hil-service --no-pager | grep -E "Active:|forward-service|hil-service"
}

# Main function
main() {
    local target="${1:-all}"
    
    log_info "HITL Deployment Script - $(date)"
    log_info "Target: $target"
    echo ""
    
    # Pull code
    pull_code
    echo ""
    
    case "$target" in
        forward)
            deploy_forward
            ;;
        hil)
            deploy_hil
            ;;
        all)
            deploy_forward
            echo ""
            deploy_hil
            ;;
        status)
            check_status
            ;;
        *)
            echo "Usage: $0 [forward|hil|all|status]"
            echo "  forward - Deploy Forward Service only"
            echo "  hil     - Deploy HIL Service only"
            echo "  all     - Deploy all services (default)"
            echo "  status  - Check service status"
            exit 1
            ;;
    esac
    
    echo ""
    check_status
    log_info "Deployment completed"
}

main "$@"
