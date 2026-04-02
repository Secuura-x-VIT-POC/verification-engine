FROM node:20

WORKDIR /workspace/frontend

COPY frontend/package.json frontend/package-lock.json ./

RUN npm ci

COPY frontend .

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
