<template>
  <div>
    <v-toolbar flat>
      <v-toolbar-title class="text-h6 font-weight-regular secondary--text text--lighten-1">Projects</v-toolbar-title>
      <v-spacer></v-spacer>
      <v-btn text small @click="loadProjects()" color="secondary">Reload
        <v-icon right>refresh</v-icon>
      </v-btn>
      <v-btn-toggle tile mandatory v-model="creatorFilter" class="mx-2">
        <v-btn>All</v-btn>
        <v-btn>Mine</v-btn>
        <v-btn>Others</v-btn>
      </v-btn-toggle>
      <v-menu>
        <template v-slot:activator="{ on, attrs }">
          <v-btn
              small
              color="primary"
              dark
              v-bind="attrs"
              v-on="on"
          >
            <v-icon left>add</v-icon>
            Add Project
          </v-btn>
        </template>
        <v-list>
          <v-list-item-group>
            <v-list-item @click="openCreateDialog=true">
              <v-list-item-content>
                New
              </v-list-item-content>
            </v-list-item>
            <v-list-item @click="openImportDialog=true">
              <v-list-item-content>
                Import
              </v-list-item-content>
            </v-list-item>
          </v-list-item-group>
        </v-list>
      </v-menu>
    </v-toolbar>

    <!-- Project list -->
    <div v-if="projects.length > 0">
      <v-card flat>
        <v-row class="px-2 py-1 caption secondary--text text--lighten-3">
          <v-col cols=2>Name</v-col>
          <v-col cols=2>Project key</v-col>
          <v-col cols=4>Description</v-col>
          <v-col cols=2>Created by</v-col>
          <v-col cols=2>Created on</v-col>
        </v-row>
      </v-card>
      <v-hover v-slot="{ hover }" v-for="p in projects" :key="p.id">
        <v-card outlined tile class="grey lighten-5 project"
                :class="[{'info': hover}]"
                :to="{name: 'project-overview', params: {id: p.id}}"
                v-show="creatorFilter === 0 || creatorFilter === 1 && p.owner.id === userProfile.id || creatorFilter === 2 && p.owner.id !== userProfile.id">
          <v-row class="pa-2">
            <v-col cols=2>
              <div class="subtitle-2 primary--text text--darken-1">{{ p.name }}</div>
            </v-col>
            <v-col cols=2>
              <div>{{ p.key }}</div>
            </v-col>
            <v-col cols=4>
              <div>{{ p.description || "-" }}</div>
            </v-col>
            <v-col cols=2>
              <div :class="{'font-weight-bold': p.owner.id === userProfile.id}">
                {{ p.owner.user_id === userProfile.user_id ? "me" : (p.owner.displayName || p.owner.user_id) }}
              </div>
            </v-col>
            <v-col cols=2>
              <div>{{ p.createdDate | date }}</div>
            </v-col>
          </v-row>
          <v-divider></v-divider>
        </v-card>
      </v-hover>
    </div>
    <v-container v-else class="font-weight-light font-italic secondary--text">
      <div v-if="isAdmin || isCreator">None created, none invited</div>
      <div v-else>You have not been invited to any projects yet</div>
    </v-container>


    <!-- Modal dialog to import new projects -->
    <v-dialog v-model="openImportDialog" width="500" persistent>
      <v-card>
        <ValidationObserver ref="dialogForm">
          <v-form @submit.prevent="prepareImport()">
            <v-card-title>Import project</v-card-title>
            <v-card-text>
              <ValidationProvider name="File" rules="required" v-slot="{errors}">
                <v-file-input accept=".zip"
                              label="Select a project to import"
                              @change="file = $event"
                              :error-messages="errors"
                ></v-file-input>
              </ValidationProvider>
            </v-card-text>
            <v-card-actions>
              <v-spacer></v-spacer>
              <v-btn color="secondary" text @click="clearAndCloseDialog()">Cancel</v-btn>
              <v-btn color="primary" text type="submit" :disabled="!file" :loading="preparingImport">Next</v-btn>
            </v-card-actions>
          </v-form>
        </ValidationObserver>
      </v-card>
    </v-dialog>

    <!-- Modal dialog to set the project key in case of conflict key while importing -->
    <v-dialog v-model="openPrepareDialog" width="500" persistent>
      <v-card>
        <ValidationObserver ref="dialogForm">
          <v-form @submit.prevent="ImportIfNoConflictKey()">
            <v-card-text>
              <div class="title">Set new key for the imported project</div>
              <ValidationProvider ref="validatorNewKey" name="Name" mode="eager" rules="required" v-slot="{errors}">
                <v-text-field label="Project Key*" type="text" v-model="newProjectKey"
                              :error-messages="errors"></v-text-field>
              </ValidationProvider>
              <div v-if="loginsImportedProject.length !== 0">
                <div class="title">Map users</div>
                <v-list
                    style="max-height: 1200px"
                    class="overflow-y-auto overflow-x-hidden">
                  <template v-for="item in loginsImportedProject">
                    <v-row align="center" justify="center" dense>
                      <v-col cols="4">
                        <div>
                          {{ item }}
                        </div>
                      </v-col>
                      <v-col cols="2" align="center">
                        <v-icon> mdi-arrow-right</v-icon>
                      </v-col>
                      <v-col cols="6">
                        <v-select hide-details dense :items="loginsCurrentInstance"
                                  v-model="mapLogins[item]"></v-select>
                      </v-col>
                    </v-row>
                  </template>
                </v-list>
              </div>
            </v-card-text>
            <v-card-actions>
              <v-spacer></v-spacer>
              <v-btn color="secondary" text @click="clearAndCloseDialog()">Cancel</v-btn>
              <v-btn color="primary" text type="submit">Import</v-btn>
            </v-card-actions>
          </v-form>
        </ValidationObserver>
      </v-card>
    </v-dialog>


    <!-- Modal dialog to create new projects -->
    <v-dialog v-model="openCreateDialog" width="500" persistent>
      <v-card>
        <ValidationObserver ref="dialogForm">
          <v-form @submit.prevent="submitNewProject()">
            <v-card-title>New project details</v-card-title>
            <v-card-text>
              <ValidationProvider name="Name" mode="eager" rules="required" v-slot="{errors}">
                <v-text-field label="Project Name*" type="text" v-model="newProjectName"
                              :error-messages="errors"></v-text-field>
              </ValidationProvider>
              <ValidationProvider name="Key" mode="eager" rules="required" v-slot="{errors}">
                <v-text-field label="Project Key*" type="text" v-model="newProjectKey"
                              :error-messages="errors"></v-text-field>
              </ValidationProvider>
              <v-text-field label="Project Description" type="text" v-model="newProjectDesc"></v-text-field>
              <div v-if="projectCreateError" class="caption error--text">{{ projectCreateError }}</div>
            </v-card-text>
            <v-card-actions>
              <v-spacer></v-spacer>
              <v-btn color="secondary" text @click="clearAndCloseDialog()">Cancel</v-btn>
              <v-btn color="primary" text type="submit">Save</v-btn>
            </v-card-actions>
          </v-form>
        </ValidationObserver>
      </v-card>
    </v-dialog>

  </div>
</template>

<script setup lang="ts">
import {computed, onMounted, ref, watch} from "vue";
import {ValidationObserver} from "vee-validate";
import {Role} from "@/enums";
import {PostImportProjectDTO, ProjectPostDTO} from "@/generated-sources";
import {toSlug} from "@/utils";
import {useRoute, useRouter} from "vue-router/composables";
import moment from "moment";
import {useUserStore} from "@/stores/user";
import {useProjectStore} from "@/stores/project";
import {api} from "@/api";
import mixpanel from "mixpanel-browser";

const route = useRoute();
const router = useRouter();

const userStore = useUserStore();
const projectStore = useProjectStore();

const openCreateDialog = ref<boolean>(false); // toggle for edit or create dialog
const openPrepareDialog = ref<boolean>(false);
const openImportDialog = ref<boolean>(false);
const newProjectName = ref<string>("");
const newProjectKey = ref<string>("");
const newProjectDesc = ref<string>("");
const creatorFilter = ref<number>(0);
const projectCreateError = ref<string>("");
const validatorNewKey = ref();
const metadataDirectoryPath = ref<string>("");
const loginsCurrentInstance = ref<string[]>([]);
const loginsImportedProject = ref<string[]>([]);
const mapLogins = ref<{ [key: string]: string }>({});
const preparingImport = ref<boolean>(false);

// template ref
const dialogForm = ref<InstanceType<typeof ValidationObserver> | null>(null);
const file = ref<File | null>(null);

onMounted(async () => {
  const f = route.query.f ? route.query.f[0] || '' : '';
  creatorFilter.value = parseInt(f) || 0;
  await loadProjects();
})

// computed
const userProfile = computed(() => {
  const userProfile = userStore.userProfile;
  if (userProfile == null) {
    throw Error("User is not defined.")
  }
  return userProfile;
});

const isAdmin = computed(() => {
  return userStore.hasAdminAccess;
});

const isCreator = computed(() => {
  return userProfile.value.roles?.includes(Role.AICREATOR);
});

const projects = computed(() => {
  return projectStore.projects
      .sort((a, b) => moment(b.createdDate).diff(moment(a.createdDate)));
})

// functions
async function loadProjects() {
  await projectStore.getProjects();
}

async function prepareImport() {
  if (!file.value) {
    return;
  }
  preparingImport.value = true;
  let formData = new FormData();
  formData.append('file', file.value);
  return await api.prepareImport(formData)
      .then(response => {
        loginsCurrentInstance.value = response.loginsCurrentInstance;
        loginsImportedProject.value = response.loginsImportedProject;
        metadataDirectoryPath.value = response.temporaryMetadataDirectory;
        openImportDialog.value = false;
        openPrepareDialog.value = true;
        loginsImportedProject.value.forEach((item, index) => {
          if (index >= loginsCurrentInstance.value.length) {
            mapLogins.value[item] = loginsCurrentInstance.value[0];
          } else {
            mapLogins.value[item] = loginsCurrentInstance.value[index];
          }
        });
        newProjectKey.value = response.projectKey;
      })
      .finally(() => preparingImport.value = false);
}

async function ImportIfNoConflictKey() {
  if (!file.value) {
    return;
  }
  let projects = projectStore.projects;
  let keyAlreadyExist: boolean = false;
  projects.forEach(project => {
    if (project.key == newProjectKey.value) keyAlreadyExist = true;
  })

  if (keyAlreadyExist) {
    validatorNewKey.value.applyResult({
      errors: ["A project with this key already exist, please change key"],
      valid: false,
      failedRules: {}
    })
  } else {
    let formData = new FormData();
    if (file) {
      formData.append('file', file.value);
    }
    mixpanel.track('Import project', {projectkey: newProjectKey.value});
    const postImportProject: PostImportProjectDTO = {
      mappedUsers: mapLogins.value,
      projectKey: newProjectKey.value,
      pathToMetadataDirectory: metadataDirectoryPath.value
    }
    api.importProject(postImportProject)
        .then((p) => {
          router.push({name: 'project-overview', params: {id: p.id}})
        })
  }
}

function clearAndCloseDialog() {
  dialogForm.value?.reset();
  openCreateDialog.value = false;
  openImportDialog.value = false;
  openPrepareDialog.value = false;
  newProjectName.value = '';
  newProjectKey.value = '';
  newProjectDesc.value = '';
  projectCreateError.value = '';
}

async function submitNewProject() {
  if (!newProjectName.value) {
    return;
  }

  const proj: ProjectPostDTO = {
    name: newProjectName.value.trim(),
    key: newProjectKey.value!.trim(),
    description: newProjectDesc.value.trim(),
    inspectionSettings: {
      limeNumberSamples: 500
    }
  };

  try {
    await projectStore.createProject(proj);
    clearAndCloseDialog();
  } catch (e) {
    console.error(e.message);
    projectCreateError.value = e.message;
  }
}

// watchers
watch(() => newProjectName.value, (value) => {
  newProjectKey.value = toSlug(value);
})

</script>

<style>
#create .v-speed-dial {
  position: absolute;
}

#create .v-btn--floating {
  position: relative;
}
</style>
