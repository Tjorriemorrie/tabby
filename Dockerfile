FROM jupyter/notebook

ADD requirements.txt .

RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN pip list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1  | xargs -n1 pip install -U
RUN jupyter nbextension enable --py widgetsnbextension --sys-prefix
