# Dev image: Vite dev server with hot reload (used by docker-compose.yml)
FROM node:22-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# Build stage for production
FROM dev AS build
RUN npm run build

# Production static image served by nginx (TLS + API proxy live in the edge nginx, see /nginx)
FROM nginx:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
