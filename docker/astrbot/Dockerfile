ARG ASTRBOT_BASE_IMAGE=m.daocloud.io/docker.io/soulter/astrbot@sha256:369164f8c2a063a6076203b8ef90be25e79be2d70c52c5317607035dece177ea
FROM ${ASTRBOT_BASE_IMAGE}

COPY packages/dududa-agent /opt/dududa/dududa-agent
COPY services/icourse-mcp /opt/dududa/icourse-mcp
COPY plugins/astrbot_plugin_dududa_core/requirements.txt /opt/dududa/dududa-core-requirements.txt
RUN python -m pip install --no-cache-dir \
    -r /opt/dududa/dududa-core-requirements.txt \
    /opt/dududa/dududa-agent \
    /opt/dududa/icourse-mcp
