# Web App Styling Guide

## Template Architecture

### Jinja2 Template Inheritance

The web app uses Jinja2's template inheritance pattern with a base template that all pages extend. This follows the official Jinja2 recommended approach for maintaining consistent layouts.

### Base Template

`services/fastapi_web_app/templates/base.html`:
- Common HTML structure, meta tags, and Tailwind CSS configuration
- Dark mode initialization script (runs before page render to prevent flash)
- Theme toggle button with sun/moon icons
- Navigation bar structure
- Reusable template blocks for customization

### Template Blocks

```jinja2
{% block title %}        # Page title
{% block extra_head %}   # Additional <head> content (styles, meta tags)
{% block body_class %}   # Custom body classes
{% block navigation %}   # Override entire nav (rare)
{% block nav_links %}    # Just the nav links (common)
{% block content %}      # Main page content (required)
{% block extra_scripts %}# Page-specific JavaScript
```

### Template Files

- `base.html`: Base layout with dark mode support
- `home.html`: Conversational chat interface (Claude Chat/ChatGPT style with full history display)
- `admin.html`: Document management (upload, list, delete)
- `about.html`: Project information page
- `upload_progress.html`: Real-time upload progress with SSE

### Usage Pattern

```jinja2
{% extends "base.html" %}

{% block title %}Page Title{% endblock %}

{% block content %}
<!-- Page-specific HTML -->
{% endblock %}

{% block extra_scripts %}
<script>
// Page-specific JavaScript
</script>
{% endblock %}
```

## Dark/Light Mode Implementation

### Strategy

- Class-based dark mode using Tailwind CSS (`darkMode: 'class'`)
- Theme stored in `localStorage` for persistence across sessions
- System preference detection on first visit via `prefers-color-scheme`
- Theme initialization script in `<head>` prevents flash of wrong theme

### Theme Toggle

```javascript
// Auto-detects system preference on first visit
const theme = localStorage.getItem('theme') ||
              (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

// Toggle via button click
document.documentElement.classList.toggle('dark');
localStorage.setItem('theme', isDark ? 'light' : 'dark');
```

### Theme State

- Light mode: No `dark` class on `<html>`
- Dark mode: `dark` class on `<html>`
- Persists across page navigation via localStorage

## Styling System

### Framework

Tailwind CSS 3.x via CDN:
- Utility-first CSS framework
- No build step required (CDN approach)
- Custom configuration for dark mode

### Configuration

```javascript
tailwind.config = {
    darkMode: 'class'  // Class-based dark mode
}
```

## Design System

### Color Palette

| Element | Light Mode | Dark Mode |
|---------|-----------|-----------|
| **Backgrounds** |
| Primary | `bg-white` | `dark:bg-gray-900` |
| Secondary | `bg-gray-50` | `dark:bg-gray-800` |
| Tertiary | `bg-gray-100` | `dark:bg-gray-700` |
| **Text** |
| Primary | `text-gray-900` | `dark:text-gray-100` |
| Secondary | `text-gray-600` | `dark:text-gray-400` |
| Tertiary | `text-gray-500` | `dark:text-gray-500` |
| **Borders** |
| Default | `border-gray-200` | `dark:border-gray-700` |
| Light | `border-gray-300` | `dark:border-gray-600` |
| **Buttons** |
| Primary | `bg-blue-600 hover:bg-blue-700` | `dark:bg-blue-500 dark:hover:bg-blue-600` |
| Success | `bg-green-600 hover:bg-green-700` | `dark:bg-green-500 dark:hover:bg-green-600` |
| Danger | `bg-red-600 hover:bg-red-900` | `dark:bg-red-400 dark:hover:bg-red-300` |
| **Accents** |
| Highlight | `bg-blue-50` | `dark:bg-blue-900/30` |
| Code | `bg-gray-100` (rgba 0.1) | `dark:bg-gray-400/20` |

### Typography

- Base font size: `text-base` (1rem / 16px)
- Headings: `text-3xl` (h1), `text-xl` (h2), `text-sm` (h3)
- Line height: `leading-relaxed` for body text

### Transitions

```css
transition-colors duration-200  /* Smooth theme switching */
```

### Special Styling

**Answer Content** (Markdown rendered from LLM):

```css
.answer-content code {
    background-color: rgba(107, 114, 128, 0.1);
    /* dark mode: rgba(156, 163, 175, 0.2) */
}

.answer-content pre {
    background-color: rgba(107, 114, 128, 0.05);
    /* dark mode: rgba(31, 41, 55, 0.5) */
}
```

## Layout Patterns

### Centered Search

home.html - no results:

```css
flex flex-col items-center justify-center  /* Vertical centering */
max-w-3xl mx-auto                          /* Horizontal centering */
```

### Results View

home.html - with results:

```css
mt-20 pb-24         /* Top margin, bottom padding for fixed input */
fixed bottom-0      /* Fixed bottom search bar */
```

### Admin Table

```css
hover:bg-gray-50 dark:hover:bg-gray-700/50  /* Row hover */
divide-y divide-gray-200 dark:divide-gray-700  /* Row dividers */
```

### LLM Context Dropdown

```html
<details class="group">
  <summary>...</summary>
  <!-- Tailwind group-open: for arrow rotation -->
</details>
```

## Validation

### Template Syntax Validation

```bash
cd services/fastapi_web_app
uv run python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
env.get_template('base.html')  # Validates syntax
"
```

**Expected Output:**
```
✓ base.html: Valid
✓ home.html: Valid
✓ admin.html: Valid
✓ about.html: Valid
✓ results.html: Valid
✓ upload_progress.html: Valid
```

## Best Practices

### 1. Extending Templates

- Always use `{% extends "base.html" %}` as first line
- Override only necessary blocks
- Use `{{ super() }}` to include parent block content when extending

### 2. Dark Mode Utilities

- Always pair light and dark variants: `bg-white dark:bg-gray-900`
- Test both themes during development
- Use semantic color names (primary, secondary) in comments

### 3. Responsive Design

- Use Tailwind responsive prefixes: `sm:px-6 lg:px-8`
- Mobile-first approach (base styles = mobile)
- Test with `w-full` and `max-w-*` containers

### 4. Accessibility

- Include `aria-label` on icon buttons
- Use semantic HTML (`<nav>`, `<main>`, `<section>`)
- Maintain sufficient color contrast in both themes

### 5. Performance

- Theme initialization before DOM render prevents flash
- Transitions limited to `transition-colors` (cheap)
- CDN Tailwind CSS for quick prototyping (consider build step for production)

## Common Styling Tasks

### Adding a New Page

```jinja2
{% extends "base.html" %}

{% block title %}New Page{% endblock %}

{% block nav_links %}
<a href="/">Home</a>
<span class="text-gray-400 dark:text-gray-500">New Page</span>
{% endblock %}

{% block content %}
<main class="max-w-5xl mx-auto mt-24 px-4">
    <!-- Page content -->
</main>
{% endblock %}
```

### Custom Theme Toggle Position

```jinja2
{% block navigation %}
<!-- Override entire nav -->
<nav class="custom-layout">
    <button id="themeToggle">...</button>
</nav>
{% endblock %}
```

### Page-Specific Styles

```jinja2
{% block extra_head %}
<style>
.custom-element {
    /* Page-specific CSS */
}
</style>
{% endblock %}
```
