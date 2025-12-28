# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage
FROM node:22-alpine AS production

WORKDIR /app

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S sveltekit -u 1001

# Copy built application and package files
COPY --from=builder /app/build build/
COPY --from=builder /app/package.json .
COPY --from=builder /app/package-lock.json .

# Install production dependencies only (npm ci is faster with lock file)
RUN npm ci --omit=dev

# Set ownership
RUN chown -R sveltekit:nodejs /app

USER sveltekit

# Expose port
EXPOSE 3000

# Environment variables
ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

# Start the server
CMD ["node", "build"]
