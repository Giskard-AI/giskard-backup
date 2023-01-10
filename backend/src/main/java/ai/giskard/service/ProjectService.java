package ai.giskard.service;


import ai.giskard.domain.Feedback;
import ai.giskard.domain.Project;
import ai.giskard.domain.User;
import ai.giskard.domain.ml.Dataset;
import ai.giskard.domain.ml.ProjectModel;
import ai.giskard.domain.ml.TestSuite;
import ai.giskard.exception.EntityAlreadyExistsException;
import ai.giskard.repository.FeedbackReplyRepository;
import ai.giskard.repository.FeedbackRepository;
import ai.giskard.repository.ProjectRepository;
import ai.giskard.repository.UserRepository;
import ai.giskard.repository.ml.DatasetRepository;
import ai.giskard.repository.ml.ModelRepository;
import ai.giskard.repository.ml.TestRepository;
import ai.giskard.repository.ml.TestSuiteRepository;
import ai.giskard.security.SecurityUtils;
import ai.giskard.utils.YAMLConverter;
import ai.giskard.utils.ZipUtils;
import ai.giskard.web.dto.mapper.GiskardMapper;
import ai.giskard.web.dto.ml.ProjectPostDTO;
import ai.giskard.web.rest.errors.Entity;
import ai.giskard.web.rest.errors.EntityNotFoundException;
import ai.giskard.web.rest.errors.NotInDatabaseException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import lombok.RequiredArgsConstructor;
import org.apache.commons.io.FileUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.FileSystemUtils;
import org.springframework.web.multipart.MultipartFile;

import javax.validation.constraints.NotNull;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

@Service
@Transactional
@RequiredArgsConstructor
public class ProjectService {
    private final UserRepository userRepository;
    private final FeedbackReplyRepository feedbackReplyRepository;
    private final FileUploadService fileUploadService;
    private final ProjectRepository projectRepository;
    private final ModelRepository modelRepository;
    private final DatasetRepository datasetRepository;
    private final FileLocationService locationService;
    private final FeedbackRepository feedbackRepository;
    private final TestSuiteRepository testSuiteRepository;
    private final TestRepository testRepository;
    final GiskardMapper giskardMapper;

    public static final Pattern PROJECT_KEY_PATTERN = Pattern.compile("^[a-z\\d_]+$");

    /**
     * Update project
     *
     * @param id         id of the project to update
     * @param projectDTO updated project
     * @return project updated
     */
    public Project update(@NotNull Long id, ProjectPostDTO projectDTO) {
        Project project = projectRepository.getById(id);
        giskardMapper.updateProjectFromDto(projectDTO, project);
        return projectRepository.save(project);
    }

    public static boolean isProjectKeyValid(String projectKey) {
        return PROJECT_KEY_PATTERN.matcher(projectKey).matches();
    }

    private void validateProjectKey(String projectKey) {
        if (!isProjectKeyValid(projectKey)) {
            throw new IllegalArgumentException(String.format("Project key %s is not valid. Project keys can contain lower case latin characters, digits and underscores", projectKey));
        }
    }

    /**
     * Create project
     */
    public Project create(Project project, String ownerLogin) {
        String projectKey = project.getKey();
        validateProjectKey(projectKey);
        projectRepository.findOneByKey(projectKey).ifPresent(p -> {
            throw new EntityAlreadyExistsException(String.format("Project with key %s already exists", projectKey));
        });
        User owner = userRepository.getOneByLogin(ownerLogin);
        project.setOwner(owner);
        return projectRepository.save(project);
    }

    /**
     * Test if the authenticated user is in the guestlist
     *
     * @param userList list of users
     * @return boolean
     */
    public boolean isUserInGuestList(Set<User> userList) {
        return userList.stream().anyMatch(guest -> guest.getLogin().equals(SecurityUtils.getCurrentAuthenticatedUserLogin()));
    }

    /**
     * Delete the project
     *
     * @param id id of the project to delete
     */
    public void delete(Long id) {
        Project project = projectRepository.getById(id);
        try {
            projectRepository.deleteById(id);
            projectRepository.flush();
            FileSystemUtils.deleteRecursively(locationService.resolvedProjectHome(project.getKey()));
        } catch (Exception e) {
            throw new GiskardRuntimeException("Failed to delete project %s".formatted(project.getKey()));
        }
    }

    public byte[] export(Long id) throws IOException {
        // Create a tmp folder
        Path temporaryExportDir = locationService.timestampMetadataDirectory();
        Files.createDirectories(temporaryExportDir);

        // Get the project from repository
        Project project = projectRepository.getById(id);
        Path homeProject = locationService.resolvedProjectHome(project.getKey());

        createMetadataYamlFiles(temporaryExportDir, project);

        // Copy content of the /giskard-home/projects/{projecKey} into the temporary newly created folder
        try {
            FileUtils.copyDirectory(homeProject.toFile(), temporaryExportDir.toFile());
        } catch (IOException e){
            throw new GiskardRuntimeException("Error while copying your project for export");
        }

        // Zip the project and send it as bytes to the Frontend
        Path projectZipPath = locationService.resolvedTmpPath().resolve(String.format("%s.zip", project.getKey()));
        if (!Files.exists(projectZipPath)){
            Files.createFile(projectZipPath);
        }
        ZipUtils.zip(temporaryExportDir, projectZipPath);

        return Files.readAllBytes(projectZipPath);
    }

    public void createMetadataYamlFiles(Path temporaryExportDirectory, Project project) throws IOException {
        // Convert every part of the project into YAML files stored into the created folder
        Path projectMetadataPath =  locationService.resolvedMetadataPath(temporaryExportDirectory, Project.class);
        Path modelsMetadatPath = locationService.resolvedMetadataPath(temporaryExportDirectory, ProjectModel.class);
        Path datasetsMetadataPath = locationService.resolvedMetadataPath(temporaryExportDirectory, Dataset.class);
        Path feedBacksMetadataPath = locationService.resolvedMetadataPath(temporaryExportDirectory, Feedback.class);
        Path testSuitesMetadataPath = locationService.resolvedMetadataPath(temporaryExportDirectory, TestSuite.class);
        YAMLConverter.exportEntityToYAML(project, projectMetadataPath);
        YAMLConverter.exportEntitiesToYAML(project.getModels(), modelsMetadatPath);
        YAMLConverter.exportEntitiesToYAML(project.getDatasets(), datasetsMetadataPath);
        YAMLConverter.exportEntitiesToYAML(project.getFeedbacks(), feedBacksMetadataPath);
        YAMLConverter.exportEntitiesToYAML(project.getTestSuites(), testSuitesMetadataPath);
    }


    public Project importProject(MultipartFile zipMultipartFile, String userName) throws IOException, NullPointerException {
        // Create a tmp folder
        Path temporaryExportDir = locationService.timestampMetadataDirectory();
        Files.createDirectories(temporaryExportDir);

        // Unzip the received file into the created folder
        Path zipFilePath = temporaryExportDir.resolve("project.zip");
        Files.createFile(zipFilePath);
        try (OutputStream os = new FileOutputStream(zipFilePath.toFile())) {
            os.write(zipMultipartFile.getBytes());
        }
        ZipUtils.unzip(zipFilePath, temporaryExportDir);

        // Get each element thanks to the metadata files
        ObjectMapper mapper = new ObjectMapper(new YAMLFactory())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
        Project project = mapper.readValue(locationService.resolvedMetadataPath(temporaryExportDir, Project.class).toFile(), Project.class);
        List<ProjectModel> models = mapper.readValue(locationService.resolvedMetadataPath(temporaryExportDir, ProjectModel.class).toFile(), new TypeReference<>(){} );
        List<Dataset> datasets = mapper.readValue(locationService.resolvedMetadataPath(temporaryExportDir, Dataset.class).toFile(), new TypeReference<>(){} );
        List<Feedback> feedbacks = mapper.readValue(locationService.resolvedMetadataPath(temporaryExportDir, Feedback.class).toFile(), new TypeReference<>(){} );
        List<TestSuite> testSuites = mapper.readValue(locationService.resolvedMetadataPath(temporaryExportDir, TestSuite.class).toFile(), new TypeReference<>(){} );

        Map<Long, Long> mapFormerNewIdModelDataset = new HashMap<>();

        // Save the project in the db (verify that key is not already used)
        Project savedProject = create(project, userName);
        String projectKey = savedProject.getKey();

        // Create a new folder for the new models and data files
        Path newProjectHome = locationService.resolvedProjectHome(projectKey);

        // Storage of each element in the db
         models.forEach(model -> {
             Long formerId = model.getId();
             Path formerModelPath = temporaryExportDir.resolve("models").resolve(FileLocationService.createZSTname("model_", formerId));
             Path formerRequirementsModelPath = temporaryExportDir.resolve("models").resolve(FileLocationService.createTXTname("model-requirements_", formerId));
             try {
                 model.setProject(savedProject);
                 FileInputStream modelStream = new FileInputStream(formerModelPath.toFile());
                 FileInputStream modelRequirementStream = new FileInputStream(formerRequirementsModelPath.toFile());
                 ProjectModel savedModel = fileUploadService.uploadModel(model, modelStream, modelRequirementStream);
                 mapFormerNewIdModelDataset.put(formerId, savedModel.getId());
             } catch (IOException e) {
                 throw new GiskardRuntimeException("Couldn't upload the models");
             }
         });

         datasets.forEach(dataset -> {
             Long formerId = dataset.getId();
             Path formerDatasetPath = temporaryExportDir.resolve("datasets").resolve(FileLocationService.createZSTname("data_", formerId));
             try{
                 FileInputStream datasetStream = new FileInputStream(formerDatasetPath.toFile());
                 Dataset savedDataset = fileUploadService.uploadDataset(savedProject, dataset.getName(), dataset.getFeatureTypes(), dataset.getColumnTypes(), dataset.getTarget(), datasetStream);
                 mapFormerNewIdModelDataset.put(formerId, savedDataset.getId());
                 Files.delete(formerDatasetPath);
             }
             catch(IOException e){
                 throw new GiskardRuntimeException("Couldn't upload the datasets");
             }
         });

         feedbacks.forEach(feedback -> {
             feedback.setProject(savedProject);
             feedback.setDataset(datasetRepository.getById(mapFormerNewIdModelDataset.get(feedback.getDataset().getId())));
             feedback.setModel(modelRepository.getById(mapFormerNewIdModelDataset.get(feedback.getModel().getId())));
             Feedback savedFeedback = feedbackRepository.save(feedback);
             feedback.getFeedbackReplies().forEach(reply -> {
                 reply.setFeedback(savedFeedback);
                 feedbackReplyRepository.save(reply);
             });
             feedbackRepository.save(savedFeedback);
         });

         testSuites.forEach(testSuite -> {
             testSuite.setProject(savedProject);
             testSuite.setActualDataset(datasetRepository.getById(mapFormerNewIdModelDataset.get(testSuite.getActualDataset().getId())));
             testSuite.setReferenceDataset(datasetRepository.getById(mapFormerNewIdModelDataset.get(testSuite.getReferenceDataset().getId())));
             testSuite.setModel(modelRepository.getById(mapFormerNewIdModelDataset.get(testSuite.getModel().getId())));
             TestSuite savedTs = testSuiteRepository.save(testSuite);
             testSuite.getTests().forEach(test -> {
                 test.setTestSuite(savedTs);
                 testRepository.save(test);
             });
             testSuiteRepository.save(savedTs);
         });

         return projectRepository.save(savedProject);
    }

    /**
     * Uninvite user from project guestlist
     *
     * @param id     id of the project
     * @param userId id of the user
     * @return update project
     */
    public Project uninvite(Long id, Long userId) {
        User user = userRepository.findById(userId).orElseThrow(() -> new EntityNotFoundException(Entity.USER, userId));
        Project project = projectRepository.findOneWithGuestsById(id).orElseThrow(() -> new EntityNotFoundException(Entity.PROJECT, id));
        project.removeGuest(user);
        projectRepository.save(project);
        return project;
    }

    /**
     * Inviting user to the project guestlist
     *
     * @param id     id of the project
     * @param userId id of the user
     * @return updated project
     */
    public Project invite(Long id, Long userId) {
        User user = userRepository.getById(userId);
        Project project = projectRepository.findOneWithGuestsById(id).orElseThrow(() -> new EntityNotFoundException(Entity.PROJECT, id));
        project.addGuest(user);
        projectRepository.save(project);
        return project;
    }

    /**
     * Listing projects accessible by the user
     * Handling access control
     *
     * @return list of projects
     */
    public List<Project> list() {
        String username = SecurityUtils.getCurrentAuthenticatedUserLogin().toLowerCase();
        User user = userRepository.findOneByLogin(username).orElseThrow(() -> new NotInDatabaseException(Entity.USER, username));
        List<Project> projects;
        if (SecurityUtils.isCurrentUserAdmin()) {
            projects = projectRepository.findAll();
        } else {
            projects = projectRepository.getProjectsByOwnerOrGuestsContains(user, user);
        }
        return projects;
    }
}
