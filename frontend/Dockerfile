# Static UI + nginx reverse proxy / load balancer. Build context is the project root:
#   docker build -f frontend/Dockerfile -t examhub-web .
FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/ /usr/share/nginx/html/
RUN rm -f /usr/share/nginx/html/Dockerfile
