FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY frontend/ ./frontend/
COPY vite.config.js ./ 2>/dev/null || true

EXPOSE 5173

CMD ["npm", "run", "dev:frontend", "--", "--host", "0.0.0.0"]
