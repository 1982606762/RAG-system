# Frontend image — TWO stages so the final image is tiny and has no Node at all.
#
# Stage 1 "build": use Node only to compile the React + TypeScript source into
# plain static files (HTML/CSS/JS) in /app/dist.
# Stage 2 "serve": throw away Node entirely; copy just those static files into
# an nginx image that serves them and reverse-proxies /api to the backend.
#
# This is why "npm isn't needed at runtime": it's a build-time tool only.

# ---- Stage 1: build the static bundle -------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

# Install deps first (cached unless package*.json changes). `npm ci` is the
# reproducible, lockfile-exact install — it needs devDependencies too because
# the build runs `tsc` (TypeScript) + `vite build`.
COPY package.json package-lock.json ./
RUN npm ci

# Copy the rest of the source and produce /app/dist.
COPY . .
RUN npm run build

# ---- Stage 2: serve with nginx --------------------------------------------
FROM nginx:alpine

# Our nginx config: serve the SPA + proxy /api to the app container.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy ONLY the built static files from stage 1 (no node_modules, no source).
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
