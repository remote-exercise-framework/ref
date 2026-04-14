<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue';
import {
  getScoreboardConfig,
  getScoreboardSubmissions,
  type ScoreboardConfig,
  type SubmissionsByChallenge,
  type ChallengeCfg,
} from '../api/scoreboard';
import { strategy } from '../ranking';
import {
  computeAssignmentStartTimes,
  getActiveAssignmentName,
  getBadges,
  parseApiDate,
} from '../ranking/util';
import RankingTable from '../components/scoreboard/RankingTable.vue';
import PointsOverTimeChart from '../components/scoreboard/PointsOverTimeChart.vue';
import ChallengePlot from '../components/scoreboard/ChallengePlot.vue';
import Countdown from '../components/scoreboard/Countdown.vue';

const POLL_INTERVAL_MS = 5000;

const config = ref<ScoreboardConfig | null>(null);
const submissions = ref<SubmissionsByChallenge>({});
const error = ref<string | null>(null);
const disabled = ref(false);

// Selections persisted across polls.
const selectedAssignment = ref<string | null>(null);
const selectedChallenge = ref<Record<string, string>>({});

let pollTimer: number | undefined;

async function refresh() {
  try {
    const [cfg, subs] = await Promise.all([
      getScoreboardConfig(),
      getScoreboardSubmissions(),
    ]);
    config.value = cfg;
    submissions.value = subs;
    error.value = null;
    disabled.value = false;
  } catch (e: unknown) {
    if (e && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404) {
      disabled.value = true;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  }
}

onMounted(async () => {
  await refresh();
  pollTimer = window.setInterval(refresh, POLL_INTERVAL_MS);
});
onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
});

const assignments = computed(() => config.value?.assignments ?? {});
const assignmentNames = computed(() => Object.keys(assignments.value));

const activeAssignment = computed<string | null>(() => {
  const names = assignmentNames.value;
  if (names.length === 0) return null;
  if (selectedAssignment.value && names.includes(selectedAssignment.value)) {
    return selectedAssignment.value;
  }
  return getActiveAssignmentName(assignments.value) ?? names[0] ?? null;
});

watch(activeAssignment, (name) => {
  if (!name) return;
  // Seed the per-assignment challenge tab on first encounter.
  if (!selectedChallenge.value[name]) {
    const firstCh = Object.keys(assignments.value[name] || {})[0];
    if (firstCh) selectedChallenge.value[name] = firstCh;
  }
});

function assignmentDisabled(name: string): boolean {
  const challenges = assignments.value[name] || {};
  const now = new Date();
  const entries = Object.values(challenges) as ChallengeCfg[];
  if (entries.length === 0) return false;
  return entries.every((ch) => {
    const s = parseApiDate(ch.start);
    return s ? s > now : true;
  }) && name !== (getActiveAssignmentName(assignments.value) ?? '');
}

function pickAssignment(name: string) {
  if (assignmentDisabled(name)) return;
  selectedAssignment.value = name;
}

function pickChallenge(assignment: string, challenge: string) {
  selectedChallenge.value = {
    ...selectedChallenge.value,
    [assignment]: challenge,
  };
}

const badges = computed(() =>
  config.value ? getBadges(assignments.value, submissions.value) : {},
);
const ranking = computed(() => {
  if (!config.value) return [];
  return strategy.getRanking(assignments.value, submissions.value);
});
const scoresOverTime = computed(() => {
  if (!config.value) return {};
  return strategy.computeChartScoresOverTime(
    assignments.value,
    submissions.value,
  );
});
const assignmentBoundaries = computed(() => {
  if (!config.value) return [];
  return computeAssignmentStartTimes(assignments.value);
});

const activeChallenges = computed(() => {
  const name = activeAssignment.value;
  if (!name) return [] as string[];
  return Object.keys(assignments.value[name] || {});
});
const activeChallengeSelected = computed<string | null>(() => {
  const name = activeAssignment.value;
  if (!name) return null;
  return (
    selectedChallenge.value[name] ??
    Object.keys(assignments.value[name] || {})[0] ??
    null
  );
});
const activeFirstChallenge = computed<ChallengeCfg | null>(() => {
  const name = activeAssignment.value;
  if (!name) return null;
  const first = Object.values(assignments.value[name] || {})[0];
  return (first as ChallengeCfg) ?? null;
});

const assignmentRanking = computed(() => {
  if (!config.value || !activeAssignment.value) return [];
  const name = activeAssignment.value;
  const subset = { [name]: assignments.value[name] || {} };
  return strategy.getRanking(subset, submissions.value);
});

const challengeRanking = computed(() => {
  if (!config.value) return [];
  const assignment = activeAssignment.value;
  const challenge = activeChallengeSelected.value;
  if (!assignment || !challenge) return [];
  const cfg = assignments.value[assignment]?.[challenge];
  if (!cfg) return [];
  const subset = { [assignment]: { [challenge]: cfg } };
  return strategy.getRanking(subset, submissions.value);
});
</script>

<template>
  <div v-if="disabled">
    <v-alert type="warning" variant="tonal">
      The scoreboard is currently disabled.
    </v-alert>
  </div>
  <div v-else-if="error && !config">
    <v-alert type="error" variant="tonal">Failed to load scoreboard: {{ error }}</v-alert>
  </div>
  <div v-else-if="!config">
    <v-progress-circular indeterminate color="secondary" />
  </div>
  <div v-else>
    <!-- Header -->
    <header style="margin-bottom: 3.5rem; display: flex; flex-direction: column; gap: 0.75rem">
      <div
        style="display: flex; align-items: center; gap: 1rem; flex-wrap: wrap"
      >
        <span class="term-live">
          <span class="term-live-dot" />LIVE
        </span>
        <span class="term-eyebrow term-hot">{{ config.course_name }}</span>
      </div>
      <h1
        class="term-display term-hot-glow"
        style="margin: 0; font-size: clamp(2.5rem, 6vw, 5rem); line-height: 0.95"
      >
        SCOREBOARD
      </h1>
    </header>

    <!-- Overall group -->
    <div class="term-group-head">
      <h2 class="term-group-title term-cool">OVERALL</h2>
    </div>

    <!-- Ranking table -->
    <section class="term-section">
      <div class="term-section-head">
        <h2 class="term-section-title">[ ranking ]</h2>
      </div>
      <RankingTable :ranking="ranking" :badges="badges" />
    </section>

    <!-- Points over time -->
    <section class="term-section">
      <div class="term-section-head">
        <h2 class="term-section-title">[ points over time ]</h2>
      </div>
      <PointsOverTimeChart
        :scores-over-time="scoresOverTime"
        :assignment-boundaries="assignmentBoundaries"
      />
    </section>

    <!-- Assignment-specific group -->
    <div class="term-group-head">
      <h2 class="term-group-title term-hot">ASSIGNMENT</h2>
    </div>

    <!-- Assignment summary: countdown + per-assignment ranking -->
    <section class="term-section">
      <div class="term-section-head">
        <h2 class="term-section-title">[ {{ activeAssignment ?? 'assignment' }} ranking ]</h2>
        <ul class="term-tabs">
          <li v-for="name in assignmentNames" :key="'as-' + name">
            <a
              :class="{
                'is-current': name === activeAssignment,
                'is-disabled': assignmentDisabled(name),
              }"
              @click.prevent="pickAssignment(name)"
              >{{ name }}</a
            >
          </li>
        </ul>
      </div>
      <div v-if="activeAssignment">
        <Countdown
          v-if="activeFirstChallenge"
          :start="activeFirstChallenge.start"
          :end="activeFirstChallenge.end"
        />
        <div style="margin-top: 1.25rem">
          <RankingTable :ranking="assignmentRanking" hide-badges />
        </div>
      </div>
    </section>

    <!-- Per-challenge plots -->
    <section class="term-section">
      <div class="term-section-head">
        <h2 class="term-section-title">[ challenges ]</h2>
      </div>
      <div v-if="activeAssignment">
        <ul class="term-tabs" style="margin: 0 0 1rem">
          <li v-for="ch in activeChallenges" :key="ch">
            <a
              :class="{ 'is-current': ch === activeChallengeSelected }"
              @click.prevent="pickChallenge(activeAssignment, ch)"
              >{{ ch }}</a
            >
          </li>
        </ul>
        <div
          v-if="activeChallengeSelected"
          style="display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, 22rem); gap: 1.25rem; align-items: start"
          class="term-challenge-grid"
        >
          <ChallengePlot
            :key="activeAssignment + '::' + activeChallengeSelected"
            :challenge-name="activeChallengeSelected"
            :assignments="assignments"
            :submissions="submissions"
          />
          <RankingTable :ranking="challengeRanking" hide-badges />
        </div>
      </div>
    </section>
  </div>
</template>
