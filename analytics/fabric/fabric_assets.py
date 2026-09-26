"""Pure Fabric item definitions shared by provisioning and static validation."""

PIPELINE_DISPLAY_NAME = "RefreshAllDemoTenants"


def demo_tenant_pipeline_definition(workspace_id: str, notebook_id: str) -> dict:
    """Build the supported two-activity controller for the single-tenant notebook."""

    def activity(name: str, tenant: str, run_global: bool, depends_on: list[dict]) -> dict:
        return {
            "name": name,
            "type": "TridentNotebook",
            "dependsOn": depends_on,
            "policy": {
                "timeout": "0.12:00:00",
                "retry": 1,
                "retryIntervalInSeconds": 30,
                "secureInput": False,
                "secureOutput": False,
            },
            "typeProperties": {
                "notebookId": notebook_id,
                "workspaceId": workspace_id,
                # String values exercise the same injection path as scheduled Fabric runs;
                # the notebook's immediately-following normalization cell validates them.
                "parameters": {
                    "TENANT": {"value": tenant, "type": "string"},
                    "RUN_GLOBAL_INSIGHTS": {
                        "value": "true" if run_global else "false",
                        "type": "string",
                    },
                },
            },
        }

    analytics_name = "Refresh Analytics"
    return {
        "properties": {
            "description": (
                "Refresh tenant analytics sequentially; Analytics owns shared global "
                "optimization and memory computations."
            ),
            "activities": [
                activity(analytics_name, "analytics", True, []),
                activity(
                    "Refresh Marvel",
                    "marvel",
                    False,
                    [{"activity": analytics_name, "dependencyConditions": ["Succeeded"]}],
                ),
            ],
        }
    }


def validate_demo_tenant_pipeline_definition(
    definition: dict, workspace_id: str, notebook_id: str
) -> None:
    """Raise ValueError unless the controller has the required safe ordering."""

    activities = definition.get("properties", {}).get("activities", [])
    if len(activities) != 2:
        raise ValueError("demo tenant pipeline must contain exactly two activities")

    analytics, marvel = activities
    if [analytics.get("name"), marvel.get("name")] != [
        "Refresh Analytics",
        "Refresh Marvel",
    ]:
        raise ValueError("demo tenant activities must remain Analytics then Marvel")
    if any(a.get("type") != "TridentNotebook" for a in activities):
        raise ValueError("demo tenant activities must be TridentNotebook activities")

    for activity in activities:
        props = activity.get("typeProperties", {})
        if props.get("workspaceId") != workspace_id or props.get("notebookId") != notebook_id:
            raise ValueError("pipeline activities must target the provisioned notebook")

    analytics_params = analytics["typeProperties"]["parameters"]
    marvel_params = marvel["typeProperties"]["parameters"]
    if analytics_params != {
        "TENANT": {"value": "analytics", "type": "string"},
        "RUN_GLOBAL_INSIGHTS": {"value": "true", "type": "string"},
    }:
        raise ValueError("Analytics must run first and own global insights")
    if marvel_params != {
        "TENANT": {"value": "marvel", "type": "string"},
        "RUN_GLOBAL_INSIGHTS": {"value": "false", "type": "string"},
    }:
        raise ValueError("Marvel must run without global insights")
    if marvel.get("dependsOn") != [
        {"activity": analytics["name"], "dependencyConditions": ["Succeeded"]}
    ]:
        raise ValueError("Marvel must depend on Analytics succeeding")
