<script setup lang="ts">
import { computed } from 'vue';
import { hoursSince } from '../../ranking/util';
import type { Highscores } from '../../ranking/util';

const props = defineProps<{
  challengeName: string;
  highscores: Highscores;
}>();

const hs = computed(() => props.highscores[props.challengeName] || null);

const score = computed(() => (hs.value ? Number(hs.value[1]).toFixed(2) : '0.00'));
const team = computed(() => (hs.value ? hs.value[0] : 'n/a'));
const ts = computed(() => (hs.value ? hoursSince(hs.value[2]) : '–'));
</script>

<template>
  <div class="term-hs-card">
    <div class="term-hs-label">{{ challengeName }}</div>
    <div class="term-hs-score">{{ score }}</div>
    <div class="term-hs-caption">{{ team }} · {{ ts }}</div>
  </div>
</template>
