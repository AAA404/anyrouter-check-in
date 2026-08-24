#!/usr/bin/env bash
# 通过 mihomo 拉取订阅、启动本地代理并探测可用节点。
# 环境变量:
#   PROXY_SUBSCRIPTION_URL  订阅链接（必填才启用）
#   PROXY_TEST_URL          探测目标，默认 https://www.google.com/generate_204
#   PROXY_TEST_URLS         额外探测目标（空格分隔），用于确认代理能访问实际服务
#   PROXY_REQUIRED          true 时探测失败则退出 1
#   PROXY_PORT              本地 mixed-port，默认 7890

set -euo pipefail

if [[ -z "${PROXY_SUBSCRIPTION_URL:-}" ]]; then
	echo "[INFO] PROXY_SUBSCRIPTION_URL not set, skip proxy setup"
	exit 0
fi

PROXY_DIR="${RUNNER_TEMP:-/tmp}/checkin-proxy"
PROXY_PORT="${PROXY_PORT:-7890}"
PROXY_TEST_URL="${PROXY_TEST_URL:-https://www.google.com/generate_204}"
PROXY_TEST_URLS="${PROXY_TEST_URLS:-${PROXY_TEST_URL}}"
MIHOMO_VERSION="${MIHOMO_VERSION:-v1.19.0}"
PROXY_REQUIRED="${PROXY_REQUIRED:-false}"

mkdir -p "${PROXY_DIR}"
cd "${PROXY_DIR}"

echo "[INFO] Downloading mihomo ${MIHOMO_VERSION}..."
ARCHIVE="mihomo-linux-amd64-${MIHOMO_VERSION}.gz"
if ! curl --retry 3 --retry-delay 5 --retry-all-errors -fsSL -o "${ARCHIVE}" \
	"https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${ARCHIVE}"; then
	echo "[WARN] Failed to download mihomo ${MIHOMO_VERSION}, skip proxy setup"
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi
gunzip -f "${ARCHIVE}"
chmod +x "mihomo-linux-amd64-${MIHOMO_VERSION}"
MIHOMO_BIN="${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}"

cat > config.yaml <<EOF
mixed-port: ${PROXY_PORT}
allow-lan: false
ipv6: false
mode: rule
log-level: warning
unified-delay: true
external-controller: 127.0.0.1:9090

proxy-providers:
  subscription:
    type: http
    url: "${PROXY_SUBSCRIPTION_URL}"
    interval: 3600
    path: ./subscription.yaml
    health-check:
      enable: true
      interval: 300
      lazy: false
      url: https://www.gstatic.com/generate_204

proxy-groups:
  - name: CHECKIN
    type: select
    use:
      - subscription

rules:
  - MATCH,CHECKIN
EOF

echo "[INFO] Starting mihomo on 127.0.0.1:${PROXY_PORT}..."
nohup "${MIHOMO_BIN}" -d "${PROXY_DIR}" -f config.yaml > mihomo.log 2>&1 &
echo $! > mihomo.pid

PROXY_URL="http://127.0.0.1:${PROXY_PORT}"
READY=false
PROBE_BODY="${PROXY_DIR}/probe-response.txt"
PROXY_NAMES=()
for _ in $(seq 1 30); do
	mapfile -t PROXY_NAMES < <(curl -fsS --max-time 2 http://127.0.0.1:9090/proxies/CHECKIN 2>/dev/null | jq -r '.all[]' 2>/dev/null || true)
	if [[ ${#PROXY_NAMES[@]} -gt 0 ]]; then
		break
	fi
	sleep 1
done
if [[ ${#PROXY_NAMES[@]} -eq 0 ]]; then
	echo "[FAILED] No proxy nodes were loaded from the subscription"
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi
echo "[INFO] Loaded ${#PROXY_NAMES[@]} proxy nodes; validating AgentRouter API responses"
selected_node_index=-1
for attempt in $(seq 1 45); do
	node_index=$(( (attempt - 1) % ${#PROXY_NAMES[@]} ))
	if [[ ${node_index} -ne ${selected_node_index} ]]; then
		node_name="${PROXY_NAMES[${node_index}]}"
		selection_payload="$(jq -nc --arg name "${node_name}" '{name: $name}')"
		if ! curl -fsS --max-time 5 -X PUT -H 'Content-Type: application/json' \
			-d "${selection_payload}" http://127.0.0.1:9090/proxies/CHECKIN >/dev/null 2>&1; then
			echo "[INFO] Unable to select proxy node $((node_index + 1))/${#PROXY_NAMES[@]}"
			continue
		fi
		selected_node_index=${node_index}
		echo "[INFO] Testing proxy node $((node_index + 1))/${#PROXY_NAMES[@]}"
		# A select group does not pre-connect like url-test. Give the newly
		# selected tunnel time to establish before the first request.
		sleep 2
	fi
	READY=true
	for test_url in ${PROXY_TEST_URLS}; do
		# AgentRouter may return a proxy-generated HTML page with HTTP 200. Its
		# OAuth state endpoint is considered healthy only when the JSON contract
		# is present, otherwise mihomo can keep selecting a unusable node.
		http_code="$(curl -sS -x "${PROXY_URL}" --max-time 20 "${test_url}" -o "${PROBE_BODY}" -w '%{http_code}' 2>/dev/null || true)"
		if [[ ! "${http_code}" =~ ^[1-4][0-9][0-9]$ ]]; then
			READY=false
			echo "[INFO] Proxy probe failed for ${test_url} (HTTP ${http_code:-no response})"
		elif [[ "${test_url}" == *"/api/oauth/state"* ]] && ! jq -e '.success == true and (.data | type == "string") and (.data | length > 0)' "${PROBE_BODY}" >/dev/null 2>&1; then
			READY=false
			echo "[INFO] Proxy probe returned non-AgentRouter JSON for ${test_url} (HTTP ${http_code})"
		fi
	done
	if [[ "${READY}" == "true" ]]; then
		READY=true
		break
	fi
	echo "[INFO] Waiting for proxy health check (${attempt}/45)..."
	sleep 2
done

if [[ "${READY}" != "true" ]]; then
	echo "[FAILED] Proxy health check failed for: ${PROXY_TEST_URLS}"
	tail -n 30 mihomo.log || true
	if [[ -f mihomo.pid ]]; then
		kill "$(cat mihomo.pid)" 2>/dev/null || true
	fi
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi

echo "[SUCCESS] Proxy is ready: ${PROXY_URL}"
echo "[INFO] Proxy is scoped to CHECKIN_PROXY_URL (browser/python only, not global HTTP_PROXY)"
if [[ -n "${GITHUB_ENV:-}" ]]; then
	echo "CHECKIN_PROXY_URL=${PROXY_URL}" >> "${GITHUB_ENV}"
fi
