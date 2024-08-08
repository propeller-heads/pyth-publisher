ARG GH_TOKEN
ARG APP_NAME=pyth-publisher
ARG APP_PACKAGE=pyth_publisher
ARG APP_PATH=/opt/$APP_NAME
ARG PYTHON_VERSION=3.9
#
# Stage: base
#

FROM continuumio/miniconda3 as base

ARG GH_TOKEN
ARG APP_NAME
ARG APP_PACKAGE
ARG APP_PATH
ARG PYTHON_VERSION

ENV \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

# Create the working directory
WORKDIR $APP_PATH

# Set up Git authentication
RUN git config --global url."https://${GH_TOKEN}@github.com/".insteadOf "https://github.com/"

# Copy environment specification
COPY requirements/requirements.txt .

# Install GCC
RUN apt-get update
RUN apt-get install -y g++

# Create conda environment and install dependencies
RUN conda create --name $APP_NAME python=$PYTHON_VERSION && \
    conda run -n $APP_NAME pip install -r requirements.txt && \
    conda clean -a

# Set conda environment
ENV PATH /opt/conda/envs/$APP_NAME/bin:$PATH
ENV CONDA_DEFAULT_ENV=$APP_NAME

#
# Stage: production
#

FROM base as production

ARG APP_NAME
ARG APP_PATH

WORKDIR $APP_PATH

# Copy the application code
COPY . .

# Ensure conda environment is activated
ENV PATH /opt/conda/envs/$APP_NAME/bin:$PATH
ENV CONDA_DEFAULT_ENV=$APP_NAME

CMD ["python", "-m", "pyth_publisher"]