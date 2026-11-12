<script setup>
// /admin/schedule: the future timetable-scheduling workspace (opened from Admin > Timetable > Schedule Class).
// For now it only shows a dialog saying the page is under development.
import { onMounted, ref } from 'vue'

const dialog = ref(null)
onMounted(() => { if (!dialog.value.open) dialog.value.showModal() })
</script>

<template>
  <main class="schedule-page">
    <dialog ref="dialog" class="sp-dialog" aria-labelledby="sp-title" aria-describedby="sp-text" @cancel.prevent>
      <span class="sp-bar" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
      <p class="sp-eyebrow">SCLASS / ADMIN / SCHEDULE</p>
      <h1 id="sp-title">Timetable scheduling</h1>
      <p id="sp-text">
        This page is under development. It will become the workspace for generating, reviewing and saving class
        timetables. For now, view room bookings in the Admin page's Timetable tab.
      </p>
      <a class="sp-back" href="/admin">Back to admin</a>
    </dialog>
  </main>
</template>

<style scoped>
.schedule-page { min-height: calc(100vh - 32px); background: #fff; }
.sp-dialog {
  width: min(460px, calc(100vw - 32px)); box-sizing: border-box; padding: 28px; border: 1px solid #e2e7ef;
  border-radius: 16px; background: #fff; color: #202124; box-shadow: 0 8px 28px rgba(60, 64, 67, .2);
  font-family: Roboto, Arial, sans-serif;
}
.sp-dialog::backdrop { background: rgba(32, 33, 36, .25); }
.sp-bar { display: flex; gap: 6px; margin-bottom: 18px; }
.sp-bar i { width: 28px; height: 4px; border-radius: 2px; }
.sp-bar i:nth-child(1) { background: #4285f4; } .sp-bar i:nth-child(2) { background: #ea4335; }
.sp-bar i:nth-child(3) { background: #fbbc04; } .sp-bar i:nth-child(4) { background: #34a853; }
.sp-eyebrow { margin: 0 0 6px; color: #5f6368; font-size: 12px; font-weight: 600; letter-spacing: .08em; }
h1 { margin: 0 0 12px; font-size: 24px; font-weight: 500; }
#sp-text { margin: 0 0 22px; color: #3c4043; line-height: 1.5; }
.sp-back {
  display: inline-block; padding: 10px 18px; border-radius: 8px; background: #1a73e8; color: #fff;
  font-weight: 600; text-decoration: none;
}
.sp-back:hover { background: #1765cc; }
.sp-back:focus-visible { outline: 2px solid #1a73e8; outline-offset: 2px; }
</style>
