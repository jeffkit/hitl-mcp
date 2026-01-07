#!/bin/bash
# =============================================================================
# HIL-MCP 部署脚本
# 
# 用法:
#   ./scripts/deploy.sh [--all|--hil-server|--forward-service|--devcloud-worker]
#
# 功能:
#   1. 拉取最新代码
#   2. 检测变更的包
#   3. 更新依赖
#   4. 构建前端（如需要）
#   5. 重启相关服务
# =============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 项目根目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PACKAGES_DIR="$PROJECT_ROOT/packages"

# 服务名称映射
declare -A SERVICE_NAMES=(
    ["hil-server"]="hil-server-direct"
    ["forward-service"]="hil-forward"
    ["devcloud-worker"]="hil-worker"
)

# 解析参数
DEPLOY_ALL=false
DEPLOY_PACKAGES=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --all)
            DEPLOY_ALL=true
            shift
            ;;
        --hil-server|--forward-service|--devcloud-worker)
            DEPLOY_PACKAGES+=("${1#--}")
            shift
            ;;
        *)
            log_error "未知参数: $1"
            echo "用法: $0 [--all|--hil-server|--forward-service|--devcloud-worker]"
            exit 1
            ;;
    esac
done

# 如果没有指定包，则检测变更
if [ ${#DEPLOY_PACKAGES[@]} -eq 0 ] && [ "$DEPLOY_ALL" = false ]; then
    log_info "检测变更的包..."
    
    # 先拉取代码
    cd "$PROJECT_ROOT"
    git fetch origin
    
    # 获取变更的文件
    CHANGED_FILES=$(git diff HEAD..origin/main --name-only 2>/dev/null || true)
    
    if [ -z "$CHANGED_FILES" ]; then
        log_info "没有检测到远程变更，拉取最新代码..."
    fi
    
    git pull origin main
    
    # 检测变更的包
    for pkg_dir in "$PACKAGES_DIR"/*/; do
        pkg_name=$(basename "$pkg_dir")
        if echo "$CHANGED_FILES" | grep -q "^packages/$pkg_name/"; then
            DEPLOY_PACKAGES+=("$pkg_name")
        fi
    done
    
    if [ ${#DEPLOY_PACKAGES[@]} -eq 0 ]; then
        log_warn "没有检测到需要部署的包"
        log_info "使用 --all 部署所有服务，或指定具体包名"
        exit 0
    fi
fi

# 如果指定 --all，部署所有 Python 包
if [ "$DEPLOY_ALL" = true ]; then
    DEPLOY_PACKAGES=("hil-server" "forward-service" "devcloud-worker")
fi

log_info "准备部署: ${DEPLOY_PACKAGES[*]}"

# 部署函数
deploy_package() {
    local pkg_name=$1
    local pkg_dir="$PACKAGES_DIR/$pkg_name"
    local service_name="${SERVICE_NAMES[$pkg_name]}"
    
    if [ ! -d "$pkg_dir" ]; then
        log_error "包目录不存在: $pkg_dir"
        return 1
    fi
    
    log_info "部署 $pkg_name..."
    cd "$pkg_dir"
    
    # 检查并创建虚拟环境
    if [ ! -d ".venv" ]; then
        log_info "  创建虚拟环境..."
        python3 -m venv .venv
    fi
    
    # 激活虚拟环境
    source .venv/bin/activate
    
    # 更新依赖
    if [ -f "pyproject.toml" ]; then
        log_info "  更新依赖..."
        if command -v uv &> /dev/null; then
            uv pip install -e .
        else
            pip install -e .
        fi
    fi
    
    # 构建前端（hil-server 特有）
    if [ "$pkg_name" = "hil-server" ] && [ -d "hil_server/console" ]; then
        log_info "  构建前端..."
        cd hil_server/console
        if command -v pnpm &> /dev/null; then
            pnpm install --frozen-lockfile
            pnpm build
        else
            npm ci
            npm run build
        fi
        cd "$pkg_dir"
    fi
    
    deactivate
    
    # 重启服务（如果服务存在）
    if [ -n "$service_name" ]; then
        if systemctl is-active --quiet "$service_name" 2>/dev/null; then
            log_info "  重启服务 $service_name..."
            sudo systemctl restart "$service_name"
            sleep 2
            if systemctl is-active --quiet "$service_name"; then
                log_success "  服务 $service_name 已重启"
            else
                log_error "  服务 $service_name 启动失败"
                return 1
            fi
        else
            log_warn "  服务 $service_name 未运行，跳过重启"
        fi
    fi
    
    log_success "$pkg_name 部署完成"
}

# 部署所有指定的包
for pkg in "${DEPLOY_PACKAGES[@]}"; do
    deploy_package "$pkg"
    echo ""
done

log_success "所有部署完成！"
