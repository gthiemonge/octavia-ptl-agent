FROM fedora:43

LABEL maintainer="Gregory Thiemonge <gthiemon@redhat.com>" \
      description="Octavia PTL daily briefing agent" \
      version="0.1.0"

RUN dnf install -y git python3 python3-pip && \
    dnf clean all && \
    rm -rf /var/cache/dnf

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml /app/
RUN python3 -c "\
import tomllib, pathlib; \
cfg = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); \
deps = cfg.get('project', {}).get('dependencies', []); \
print('\n'.join(deps))" > /tmp/deps.txt && \
    pip install --no-cache-dir -r /tmp/deps.txt && \
    rm /tmp/deps.txt

COPY . /app
RUN pip install --no-cache-dir .

ENTRYPOINT ["ptl"]
