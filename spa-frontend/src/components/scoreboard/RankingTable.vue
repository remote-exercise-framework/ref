<script setup lang="ts">
import type { Ranking } from '../../ranking/types';
import type { Badges } from '../../ranking/util';

const props = withDefaults(
  defineProps<{
    ranking: Ranking;
    badges?: Badges;
    hideBadges?: boolean;
  }>(),
  { badges: () => ({}), hideBadges: false },
);

function badgeSrc(name: string): string {
  return `/static/badges/${name}.svg`;
}

function onBadgeError(e: Event) {
  const img = e.target as HTMLImageElement;
  img.onerror = null;
  img.src = '/static/badges/default.svg';
}

const colSpan = props.hideBadges ? 3 : 4;
</script>

<template>
  <div class="term-panel">
    <table class="term-table">
      <thead>
        <tr>
          <th class="term-col-rank">#</th>
          <th>Team</th>
          <th v-if="!hideBadges">Badges</th>
          <th class="term-col-points">Points</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!ranking || ranking.length === 0" class="term-empty">
          <td :colspan="colSpan">// awaiting submissions</td>
        </tr>
        <tr v-for="([team, score], i) in ranking" :key="team">
          <td class="term-col-rank"><span class="term-rank">{{ i + 1 }}</span></td>
          <td class="term-team">{{ team }}</td>
          <td v-if="!hideBadges">
            <span class="term-badges">
              <img
                v-for="b in badges[team] || []"
                :key="b"
                :src="badgeSrc(b)"
                :alt="b"
                :title="b"
                @error="onBadgeError"
              />
            </span>
          </td>
          <td class="term-col-points">
            <span class="term-points">{{ Number(score).toFixed(2) }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
