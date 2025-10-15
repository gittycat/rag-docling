# Development Dockerfile for SvelteKit webapp with hot-reload

FROM node:22-slim

WORKDIR /app

# Copy package files
COPY package.json ./

# Install dependencies
RUN npm install

# Expose dev server port
EXPOSE 5173

# Run dev server with host binding for Docker
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
