// Facts for the intake infographics, from GET /api/admin/intakes rows
// (each carries student_intakes(student_id, group_number) and course_offerings(id)).
export function intakeFacts(intake) {
  const members = intake.student_intakes || []
  const perGroup = Array.from({ length: Math.max(intake.max_group || 1, ...members.map(m => m.group_number || 0)) }, () => 0)
  for (const member of members) if (member.group_number >= 1) perGroup[member.group_number - 1]++
  return {
    students: members.length,
    groups: intake.max_group || 0,
    groupsInUse: perGroup.filter(count => count > 0).length,
    courses: (intake.course_offerings || []).length,
    perGroup,
  }
}

export function intakeTotals(intakes) {
  const students = new Set(intakes.flatMap(intake => (intake.student_intakes || []).map(m => m.student_id)))
  const facts = intakes.map(intakeFacts)
  const memberships = facts.reduce((sum, f) => sum + f.students, 0)
  const groupsInUse = facts.reduce((sum, f) => sum + f.groupsInUse, 0)
  return {
    intakes: intakes.length,
    students: students.size,
    groups: facts.reduce((sum, f) => sum + f.groups, 0),
    perGroup: groupsInUse ? Math.round(memberships / groupsInUse) : 0,
  }
}
