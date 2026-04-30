FROM node:20-slim

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./

RUN npm install
ENV PATH=/app/frontend/node_modules/.bin:$PATH

COPY frontend /app/frontend

ENV HOST=0.0.0.0 \
    PORT=5173

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
