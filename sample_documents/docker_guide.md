# Docker Container Guide

Docker is a platform for developing, shipping, and running applications in containers. Containers package software with all its dependencies, ensuring consistency across different environments.

## What are Containers?

Containers are lightweight, standalone executable packages that include everything needed to run an application:
- Code
- Runtime
- System tools
- System libraries
- Settings

## Key Docker Concepts

### Images
Docker images are read-only templates used to create containers. They contain:
- Application code
- Runtime environment
- Dependencies
- Configuration files

### Containers
Containers are running instances of Docker images. They are:
- Isolated from other containers
- Portable across systems
- Lightweight (share host OS kernel)

### Dockerfile
A Dockerfile is a text file with instructions to build a Docker image. Common commands:
- `FROM`: Base image
- `WORKDIR`: Set working directory
- `COPY`: Copy files into image
- `RUN`: Execute commands
- `CMD`: Default command to run

### Docker Compose
Docker Compose is a tool for defining and running multi-container applications using a YAML file.

Example docker-compose.yml:
```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
  db:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: secret
```

## Common Commands

```bash
# Build image
docker build -t myapp .

# Run container
docker run -p 8000:8000 myapp

# List running containers
docker ps

# Stop container
docker stop <container_id>

# View logs
docker logs <container_id>

# Start Compose services
docker-compose up -d

# Stop Compose services
docker-compose down
```

## Best Practices

1. **Use Official Images**: Start with official base images from Docker Hub
2. **Minimize Layers**: Combine RUN commands to reduce image size
3. **Use .dockerignore**: Exclude unnecessary files from build context
4. **Don't Run as Root**: Create unprivileged users in containers
5. **Use Multi-stage Builds**: Reduce final image size
6. **Set Resource Limits**: Prevent containers from consuming all system resources

## Networking

Docker provides several networking modes:
- **bridge**: Default network, isolated from host
- **host**: Share host's network stack
- **none**: No networking
- **custom**: User-defined networks for container communication

## Volumes

Volumes persist data beyond container lifecycle:
- Named volumes: Managed by Docker
- Bind mounts: Map host directories to container
- tmpfs: In-memory storage

## Security Considerations

- Keep images updated
- Scan for vulnerabilities
- Use secrets management
- Limit container privileges
- Enable Docker Content Trust
- Use read-only file systems when possible
