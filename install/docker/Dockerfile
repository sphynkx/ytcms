FROM fedora:40

RUN dnf -y update && dnf -y install dnf-plugins-core git wget

RUN dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
    https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

RUN dnf install -y \
    python3.12 \
    python3.12-devel \
    python3-pip \
    gcc \
    gcc-c++ \
    ffmpeg \
    ffmpeg-devel \
    pkgconf-pkg-config \
    findutils \
    && dnf clean all

WORKDIR /app

COPY install/requirements.txt .

RUN pip3.12 install --upgrade pip && \
    pip3.12 install --no-cache-dir -r requirements.txt && \
    pip3.12 install --no-cache-dir nvidia-cudnn-cu12==9.1.0.70 nvidia-cublas-cu12==12.1.3.1

ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/lib64/python3.12/site-packages/nvidia/cudnn/lib:/usr/lib64/python3.12/site-packages/nvidia/cublas/lib:$LD_LIBRARY_PATH

COPY . .

RUN mkdir -p /tmp/ytcms
EXPOSE 9099

CMD ["python3", "run.py"]