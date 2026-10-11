package staff.android.pulse
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.unit.dp
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.Alignment
import org.json.JSONObject
const val ABOUT="Pulse requests reports from a real bounded local queue. A terminal worker claims and completes deterministic reports using lease fences. Four outstanding jobs, two per tenant and one worker are teaching limits, not measured production capacity."
fun validateView(d:JSONObject){
    require(d.get("sourceVersion") is Int && d.getInt("sourceVersion") > 0)
    val rows = d.getJSONArray("jobs")
    require(rows.length() <= 100)
    for (i in 0 until rows.length()) {
        val j = rows.getJSONObject(i)
        require(j.getString("status") in setOf("QUEUED", "RUNNING", "COMPLETE"))
        require(j.get("sourceVersion") is Int)
        require(j.getString("tenant") in setOf("studio", "garden", "market"))
        require(j.getString("report") in setOf("weekly", "monthly"))
    }
}
@Composable fun Product(state: CaseState, model: CaseModel, tenant: String, chooseTenant: (String) -> Unit, selectedReport: String, selectReport: (String) -> Unit) {
    val rows = state.data?.getJSONArray("jobs")
    val jobs = if (rows == null) emptyList() else (0 until rows.length()).map { rows.getJSONObject(it) }.filter { it.getString("tenant") == tenant }.reversed()
    val selected = jobs.find { it.getString("id") == selectedReport }
    Text("WORKSPACE REPORTS", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for (workspace in listOf("studio", "garden", "market")) FilterChip(selected = tenant == workspace, onClick = { chooseTenant(workspace) }, label = { Text(workspace.replaceFirstChar { it.uppercase() }) }, modifier = Modifier.testTag("workspace-$workspace"))
    }
    if (selected != null) {
        TextButton(onClick = { selectReport("") }, modifier = Modifier.testTag("back-report")) { Text("Back to reports") }
        Text("${selected.getString("report").replaceFirstChar { it.uppercase() }} report", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
        Text("${tenant.replaceFirstChar { it.uppercase() }} · edition ${selected.getInt("sourceVersion")}", color = MaterialTheme.colorScheme.onSurfaceVariant)
        val result = selected.optJSONObject("result")
        if (result != null) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                ReportMetric("Visits", result.getInt("visits")); ReportMetric("Orders", result.getInt("orders"))
            }
            Text("Completed from the source edition shown above. Request a new report after the source changes to see a newer edition.")
        } else InfoCard(if (selected.getString("status") == "RUNNING") "Preparing your report" else "Report queued", "You can return to your reports while the local worker finishes. Refresh to check its status.")
        return
    }
    Text("${tenant.replaceFirstChar { it.uppercase() }} reports", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text("Choose a reporting period", color = MaterialTheme.colorScheme.onSurfaceVariant)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        for (period in listOf("weekly", "monthly")) Button(onClick = { model.send("request", JSONObject().put("tenant", tenant).put("report", period)) }, enabled = ready(state) && state.data != null, modifier = Modifier.testTag("request-$period")) { Text("${period.replaceFirstChar { it.uppercase() }} report") }
    }
    HorizontalDivider()
    Text("Recent reports", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
    if (rows == null) Text(if (state.busy) "Loading reports…" else "Reports are unavailable. Connect to the local service and refresh.")
    else if (jobs.isEmpty()) InfoCard("Your first report", "Request a weekly or monthly report for this workspace. Its progress and result will appear here.")
    for (job in jobs) {
        val result = job.optJSONObject("result")
        Card(onClick = { selectReport(job.getString("id")) }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth().testTag("report-${job.getString("id")}")) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("${job.getString("report").replaceFirstChar { it.uppercase() }} report", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text(when (job.getString("status")) { "COMPLETE" -> "Ready"; "RUNNING" -> "Preparing"; else -> "Queued" }, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                }
                Text("Edition ${job.getInt("sourceVersion")}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (result != null) Text("${result.getInt("visits")} visits · ${result.getInt("orders")} orders")
                else Text(if (job.getString("status") == "RUNNING") "Preparing your report" else "Waiting for the local worker", style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
    Text("Local demonstration workspace · deterministic reports", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable private fun ReportMetric(label: String, value: Int) {
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.widthIn(min = 140.dp).padding(22.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(value.toString(), style = MaterialTheme.typography.headlineLarge, fontWeight = FontWeight.Bold)
            Text(label, style = MaterialTheme.typography.titleMedium)
        }
    }
}
