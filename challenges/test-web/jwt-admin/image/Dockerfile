FROM node:18-slim
WORKDIR /app
# Flag baked into image at build time
RUN echo 'CTF{jwt_none_alg_unsigned_forgery}' > /flag.txt
COPY package.json .
RUN npm install --omit=dev
COPY app.js .
EXPOSE 3000
CMD ["node", "app.js"]
