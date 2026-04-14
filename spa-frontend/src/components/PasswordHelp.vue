<script setup lang="ts">
defineProps<{
  minLength: number;
  minClasses: number;
}>();
</script>

<template>
  <div class="term-muted" style="font-size: 0.75rem; letter-spacing: 0.05em">
    Password must be at least {{ minLength }} characters and use at least
    {{ minClasses }} of: digits, uppercase, lowercase, symbols.
  </div>
</template>
