<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { parseApiDate } from '../../ranking/util';

const props = defineProps<{ start: string; end: string }>();

const now = ref(Date.now());
let timer: number | undefined;

onMounted(() => {
  timer = window.setInterval(() => (now.value = Date.now()), 500);
});
onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer);
});

const info = computed(() => {
  const start = parseApiDate(props.start);
  const end = parseApiDate(props.end);
  if (!start || !end) return { label: 'Remaining: –', width: 0 };
  const diff = end.getTime() - now.value;
  if (diff <= 0) return { label: 'Remaining: 00h 00m 00s', width: 100 };

  const totalSeconds = Math.floor(diff / 1000);
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const hms = `${String(h).padStart(2, '0')}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  const label = d > 0 ? `Remaining: ${d}d ${hms}` : `Remaining: ${hms}`;

  const total = (end.getTime() - start.getTime()) / 1000;
  const elapsed = (now.value - start.getTime()) / 1000;
  const width = Math.max(0, Math.min(100, (elapsed / total) * 100));
  return { label, width };
});
</script>

<template>
  <div class="term-countdown">
    <div class="term-countdown-label">{{ info.label }}</div>
    <div class="term-countdown-bar">
      <div class="term-countdown-fill" :style="{ width: info.width + '%' }" />
    </div>
  </div>
</template>
